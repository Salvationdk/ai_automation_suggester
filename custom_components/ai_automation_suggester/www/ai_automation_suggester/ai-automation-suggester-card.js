class AIAutomationSuggesterCard extends HTMLElement {
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
    // Determine title and filter based on config
    const typeFilter = this.config.suggestion_type || "all"; // 'all', 'fix', 'new', 'blueprint'
    
    let title = "AI Automation Suggestions";
    let icon = "mdi:robot";
    let headerColor = "var(--primary-color)";

    if (typeFilter === "fix") {
      title = "AI Repair Center";
      icon = "mdi:wrench-clock";
      headerColor = "#F44336"; // Red
    } else if (typeFilter === "blueprint") {
      title = "AI Architect (Blueprints)";
      icon = "mdi:floor-plan";
      headerColor = "#9C27B0"; // Purple
    } else if (typeFilter === "new") {
      title = "AI Inspiration";
      icon = "mdi:lightbulb-on";
      headerColor = "#2196F3"; // Blue
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
           <span style="font-size: 0.8em; opacity: 0.6; align-self: center;">Filter: ${typeFilter.toUpperCase()}</span>
           <mwc-button id="generate-btn">
              <ha-icon icon="mdi:creation" style="margin-right: 8px;"></ha-icon> Generate New
            </mwc-button>
        </div>
      </ha-card>
    `;
    
    this.content = this.querySelector("#suggestions-container");
    this.querySelector("#refresh-btn").addEventListener("click", () => this.fetchSuggestions());
    this.querySelector("#generate-btn").addEventListener("click", () => this.triggerGeneration());
    
    // Initial Fetch
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
    try {
        await this._hass.callService("ai_automation_suggester", "generate_suggestions", {});
        // Wait a bit then refresh
        setTimeout(() => this.fetchSuggestions(), 4000); 
        // Also poll longer in case it's slow
        setTimeout(() => this.fetchSuggestions(), 12000); 
    } catch (err) {
        this.content.innerHTML = `<div class="error">Generation Failed: ${err.message}</div>`;
    }
  }

  renderSuggestions(suggestions) {
    const filter = this.config.suggestion_type || "all";
    
    // Filter the list
    const filtered = suggestions.filter(item => {
        if (filter === "all") return true;
        // Fix sloppy AI typing (case insensitive)
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
          No suggestions found for filter: <b>${filter}</b>.<br>
          <small>Everything looks good, or try generating new ideas.</small>
        </div>`;
      return;
    }

    this.content.innerHTML = "";
    
    filtered.forEach(item => {
      const card = document.createElement('div');
      card.className = 'suggestion-item';
      
      // Dynamic Colors
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
                <div class="s-title">${item.title}</div>
                <div class="s-desc">${item.detailedDescription}</div>
             </div>
          </div>
          
          <div class="code-preview">
            <pre><code>${this.escapeHtml(item.yamlCode)}</code></pre>
          </div>

          <div class="suggestion-actions">
            <mwc-button class="btn-decline" data-id="${item.id}">Ignore</mwc-button>
            <mwc-button raised class="btn-accept" data-id="${item.id}" style="--mdc-theme-primary: ${typeColor};">Accept</mwc-button>
          </div>
        </div>
      `;

      card.querySelector('.btn-accept').addEventListener('click', () => this.handleAction('accept', item.id));
      card.querySelector('.btn-decline').addEventListener('click', () => this.handleAction('decline', item.id));

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

const style = document.createElement('style');
style.textContent = `
  .ai-card { overflow: hidden; }
  .suggestion-item {
    border-bottom: 1px solid var(--divider-color);
    padding: 16px;
  }
  .suggestion-item:last-child { border-bottom: none; }
  .suggestion-top { display: flex; gap: 16px; margin-bottom: 12px; }
  .s-title { font-weight: bold; font-size: 1.1em; margin-bottom: 4px; }
  .s-desc { font-size: 0.9em; opacity: 0.8; line-height: 1.4; }
  .code-preview {
    background: var(--primary-background-color);
    border: 1px solid var(--divider-color);
    padding: 8px;
    border-radius: 4px;
    font-family: monospace;
    font-size: 0.8em;
    overflow-x: auto;
    margin-bottom: 12px;
    max-height: 200px;
  }
  .suggestion-actions { display: flex; justify-content: flex-end; gap: 8px; }
  .loading, .error, .no-data { padding: 32px; text-align: center; color: var(--secondary-text-color); }
  .rotating { animation: rotation 2s infinite linear; }
  @keyframes rotation { from { transform: rotate(0deg); } to { transform: rotate(359deg); } }
`;
document.head.appendChild(style);

customElements.define("ai-automation-suggester-card", AIAutomationSuggesterCard);
