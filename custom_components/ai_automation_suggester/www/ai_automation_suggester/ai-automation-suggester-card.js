// ─────────────────────────────────────────────────────────────
// MAIN CARD CLASS v2.0 (Multi-Provider Aware)
// ─────────────────────────────────────────────────────────────
class AIAutomationSuggesterCard extends HTMLElement {
  static getStubConfig() {
    return { 
      title: "AI Suggestions", 
      suggestion_type: "all",
      provider_config: "" 
    };
  }

  static getConfigElement() {
    return document.createElement("ai-automation-suggester-card-editor");
  }

  setConfig(config) {
    this.config = config;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.content) {
      this.initCard();
    }
  }

  initCard() {
    const typeFilter = this.config.suggestion_type || "all"; 
    
    let title = "AI Automation Suggestions";
    let icon = "mdi:robot";
    let headerColor = "var(--primary-color)";

    if (typeFilter === "fix") {
      title = "AI Repair Center";
      icon = "mdi:wrench-clock";
      headerColor = "#F44336";
    } else if (typeFilter === "blueprint") {
      title = "AI Architect (Blueprints)";
      icon = "mdi:floor-plan";
      headerColor = "#9C27B0";
    } else if (typeFilter === "new") {
      title = "AI Inspiration";
      icon = "mdi:lightbulb-on";
      headerColor = "#2196F3";
    }

    this.innerHTML = `
      <ha-card class="ai-card">
        <div class="card-header" style="background-color: ${headerColor}; color: white; padding: 16px; display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 10px; font-weight: 500; font-size: 1.2rem;">
            <ha-icon icon="${icon}"></ha-icon> ${this.config.title || title}
          </div>
          <div class="header-actions">
             <mwc-icon-button id="refresh-btn">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </mwc-icon-button>
          </div>
        </div>
        
        <div class="card-content" id="suggestions-container">
          <div class="loading">Loading intelligence...</div>
        </div>
        
        <div class="card-actions" style="display: flex; justify-content: space-between; padding: 8px 16px;">
            <span style="font-size: 0.8em; opacity: 0.6; align-self: center;">View: ${typeFilter.toUpperCase()}</span>
            <mwc-button id="generate-btn">
              <ha-icon icon="mdi:creation" style="margin-right: 8px;"></ha-icon> Generate New
            </mwc-button>
        </div>
      </ha-card>
    `;
    
    this.content = this.querySelector("#suggestions-container");
    this.querySelector("#refresh-btn").addEventListener("click", () => this.fetchSuggestions());
    this.querySelector("#generate-btn").addEventListener("click", () => this.triggerGeneration());
    
    this.fetchSuggestions();
  }

  async fetchSuggestions() {
    this.content.innerHTML = '<div class="loading"><ha-circular-progress active></ha-circular-progress> Analysing Home Assistant...</div>';
    
    try {
      const suggestions = await this._hass.callApi("GET", "ai_automation_suggester/suggestions");
      this.renderSuggestions(suggestions);
    } catch (err) {
      console.error(err);
      this.content.innerHTML = `<div class="error">Connection Error: ${err.message}</div>`;
    }
  }

  async triggerGeneration() {
    this.content.innerHTML = '<div class="loading"><ha-icon icon="mdi:brain" class="rotating"></ha-icon> AI is thinking... (This takes 10-20s)</div>';
    
    // Brug provider_config fra konfigurationen hvis den findes
    const serviceData = {};
    if (this.config.provider_config) {
        serviceData.provider_config = this.config.provider_config;
    }

    try {
        await this._hass.callService("ai_automation_suggester", "generate_suggestions", serviceData);
        setTimeout(() => this.fetchSuggestions(), 5000); 
        setTimeout(() => this.fetchSuggestions(), 15000); 
    } catch (err) {
        this.content.innerHTML = `<div class="error">Generation Failed: ${err.message}</div>`;
    }
  }

  renderSuggestions(suggestions) {
    const filter = this.config.suggestion_type || "all";
    
    const filtered = suggestions.filter(item => {
        if (filter === "all") return true;
        const type = (item.type || "").toLowerCase();
        if (filter === "fix") return type.includes("fix") || type.includes("repair");
        if (filter === "blueprint") return type.includes("blueprint");
        if (filter === "new") return type.includes("new") || type.includes("improvement");
        return true;
    });

    if (!filtered || filtered.length === 0) {
      this.content.innerHTML = `
        <div class="no-data">
          <ha-icon icon="mdi:check-circle-outline" style="font-size: 3em; opacity: 0.3;"></ha-icon><br>
          No suggestions found.<br>
          <small>Try generating new ideas with your AI provider.</small>
        </div>`;
      return;
    }

    this.content.innerHTML = "";
    
    filtered.forEach(item => {
      const card = document.createElement('div');
      card.className = 'suggestion-item';
      
      let typeColor = "#2196F3"; 
      let icon = "mdi:lightbulb-on";
      const t = (item.type || "").toLowerCase();

      if (t.includes("fix")) { typeColor = "#F44336"; icon = "mdi:alert-decagram"; }
      else if (t.includes("blueprint")) { typeColor = "#9C27B0"; icon = "mdi:floor-plan"; }
      else if (t.includes("improvement")) { typeColor = "#4CAF50"; icon = "mdi:update"; }

      card.innerHTML = `
        <div class="suggestion-body">
          <div class="suggestion-top">
             <ha-icon icon="${icon}" style="color: ${typeColor};"></ha-icon>
             <div class="suggestion-main-text">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div class="s-title">${item.title}</div>
                    <div class="provider-badge">${item.provider || 'AI'}</div>
                </div>
                <div class="s-desc">${item.detailedDescription}</div>
             </div>
          </div>
          <div class="code-preview">
            <pre><code>${this.escapeHtml(item.yamlCode)}</code></pre>
          </div>
          <div class="suggestion-actions">
            <mwc-button class="btn-decline" data-id="${item.suggestion_id}">Ignore</mwc-button>
            <mwc-button raised class="btn-accept" data-id="${item.suggestion_id}" style="--mdc-theme-primary: ${typeColor};">Accept</mwc-button>
          </div>
        </div>
      `;

      card.querySelector('.btn-accept').addEventListener('click', () => this.handleAction('accept', item.suggestion_id));
      card.querySelector('.btn-decline').addEventListener('click', () => this.handleAction('decline', item.suggestion_id));

      this.content.appendChild(card);
    });
  }

  async handleAction(action, id) {
    try {
        await this._hass.callApi("POST", `ai_automation_suggester/${action}/${id}`);
        this.fetchSuggestions(); 
    } catch (err) {
        alert(`Error: ${err.message}`);
    }
  }

  escapeHtml(text) {
    if (!text) return "";
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  getCardSize() { return 4; }
}

// ─────────────────────────────────────────────────────────────
// VISUAL EDITOR CLASS
// ─────────────────────────────────────────────────────────────
class AIAutomationSuggesterCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this.render();
  }

  configChanged(newConfig) {
    const event = new CustomEvent("config-changed", {
      detail: { config: newConfig },
      bubbles: true,
      composed: true,
    });
    this.dispatchEvent(event);
  }

  render() {
    this.innerHTML = `
      <div style="padding: 12px; display: flex; flex-direction: column; gap: 16px;">
        <ha-textfield
          label="Title (Optional)"
          .value="${this._config.title || ''}"
          configValue="title"
          style="width: 100%;"
        ></ha-textfield>

        <ha-select
          label="Filter Dashboard By Type"
          .value="${this._config.suggestion_type || 'all'}"
          configValue="suggestion_type"
          fixedMenuPosition
          naturalMenuWidth
          style="width: 100%;"
        >
          <mwc-list-item value="all">All Suggestions</mwc-list-item>
          <mwc-list-item value="fix">🔧 Repair Center</mwc-list-item>
          <mwc-list-item value="blueprint">📐 Blueprints</mwc-list-item>
          <mwc-list-item value="new">💡 New Ideas</mwc-list-item>
        </ha-select>

        <ha-textfield
          label="Target Provider Entry ID (Optional)"
          .value="${this._config.provider_config || ''}"
          configValue="provider_config"
          style="width: 100%;"
        ></ha-textfield>
        <p style="opacity: 0.6; font-size: 0.85em; margin-top: -10px;">
          Leave empty to use the default AI provider for new generations.
        </p>
      </div>
    `;

    const titleInput = this.querySelector("ha-textfield[configValue='title']");
    const typeInput = this.querySelector("ha-select");
    const providerInput = this.querySelector("ha-textfield[configValue='provider_config']");

    titleInput.addEventListener("input", (e) => {
      this.configChanged({ ...this._config, title: e.target.value });
    });

    typeInput.addEventListener("selected", (e) => {
      this.configChanged({ ...this._config, suggestion_type: e.target.value });
    });

    providerInput.addEventListener("input", (e) => {
        this.configChanged({ ...this._config, provider_config: e.target.value });
    });
  }
}

// ─────────────────────────────────────────────────────────────
// STYLES
// ─────────────────────────────────────────────────────────────
if (!document.querySelector('#ai-suggester-styles')) {
    const style = document.createElement('style');
    style.id = 'ai-suggester-styles';
    style.textContent = `
      .ai-card { overflow: hidden; }
      .suggestion-item { border-bottom: 1px solid var(--divider-color); padding: 16px; position: relative; }
      .suggestion-item:last-child { border-bottom: none; }
      .suggestion-top { display: flex; gap: 16px; margin-bottom: 12px; }
      .s-title { font-weight: bold; font-size: 1.1em; margin-bottom: 4px; padding-right: 10px; }
      .s-desc { font-size: 0.9em; opacity: 0.8; line-height: 1.4; }
      .provider-badge { 
        font-size: 0.65rem; 
        background: var(--secondary-background-color); 
        color: var(--secondary-text-color); 
        padding: 2px 6px; 
        border-radius: 4px; 
        border: 1px solid var(--divider-color);
        text-transform: uppercase;
        font-weight: bold;
        white-space: nowrap;
      }
      .code-preview {
        background: var(--primary-background-color);
        border: 1px solid var(--divider-color);
        padding: 8px; border-radius: 4px;
        font-family: monospace; font-size: 0.8em;
        overflow-x: auto; margin-bottom: 12px; max-height: 200px;
      }
      .suggestion-actions { display: flex; justify-content: flex-end; gap: 8px; }
      .loading, .error, .no-data { padding: 32px; text-align: center; color: var(--secondary-text-color); }
      .rotating { animation: rotation 2s infinite linear; display: inline-block; }
      @keyframes rotation { from { transform: rotate(0deg); } to { transform: rotate(359deg); } }
    `;
    document.head.appendChild(style);
}

customElements.define("ai-automation-suggester-card", AIAutomationSuggesterCard);
customElements.define("ai-automation-suggester-card-editor", AIAutomationSuggesterCardEditor);
