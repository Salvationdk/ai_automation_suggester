class AIAutomationSuggesterCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this.content) {
      this.innerHTML = `
        <ha-card header="AI Automation Suggestions">
          <div class="card-content" id="suggestions-container">
            <div class="loading">Loading suggestions...</div>
          </div>
          <div class="card-actions">
            <mwc-button id="refresh-btn">
              <ha-icon icon="mdi:refresh"></ha-icon> Refresh
            </mwc-button>
            <mwc-button id="generate-btn">
              <ha-icon icon="mdi:creation"></ha-icon> Generate New
            </mwc-button>
          </div>
        </ha-card>
      `;
      this.content = this.querySelector("#suggestions-container");
      this.querySelector("#refresh-btn").addEventListener("click", () => this.fetchSuggestions());
      this.querySelector("#generate-btn").addEventListener("click", () => this.triggerGeneration());
      
      // Fetch data immediately
      this.fetchSuggestions();
    }
  }

  async fetchSuggestions() {
    this.content.innerHTML = '<div class="loading"><ha-circular-progress active></ha-circular-progress> Fetching AI data...</div>';
    
    try {
      // Call the new API endpoint we created in __init__.py
      const suggestions = await this._hass.callApi("GET", "ai_automation_suggester/suggestions");
      this.renderSuggestions(suggestions);
    } catch (err) {
      console.error(err);
      this.content.innerHTML = `<div class="error">Error loading suggestions: ${err.message}</div>`;
    }
  }

  async triggerGeneration() {
    this.content.innerHTML = '<div class="loading">Asking AI to generate new ideas (this takes time)...</div>';
    try {
        await this._hass.callService("ai_automation_suggester", "generate_suggestions", {});
        // Poll for updates or wait a bit? For now we just notify user.
        // Ideally, setup a listener, but for simplicity:
        setTimeout(() => this.fetchSuggestions(), 5000); 
    } catch (err) {
        this.content.innerHTML = `<div class="error">Failed to trigger generation: ${err.message}</div>`;
    }
  }

  renderSuggestions(suggestions) {
    if (!suggestions || suggestions.length === 0) {
      this.content.innerHTML = '<div class="no-data">No suggestions available. Click "Generate New".</div>';
      return;
    }

    this.content.innerHTML = "";
    
    suggestions.forEach(item => {
      const card = document.createElement('div');
      card.className = 'suggestion-item';
      
      // Determine color based on type
      let typeColor = "#2196F3"; // Blue (New)
      let icon = "mdi:lightbulb-on";
      if (item.type === "fix") { typeColor = "#F44336"; icon = "mdi:alert-decagram"; } // Red
      if (item.type === "blueprint") { typeColor = "#9C27B0"; icon = "mdi:floor-plan"; } // Purple
      if (item.type === "improvement") { typeColor = "#4CAF50"; icon = "mdi:update"; } // Green

      card.innerHTML = `
        <div class="suggestion-header" style="border-left: 5px solid ${typeColor};">
          <div class="suggestion-title">
            <ha-icon icon="${icon}" style="color: ${typeColor}; margin-right: 8px;"></ha-icon>
            <b>${item.title}</b>
            <span class="suggestion-badge" style="background:${typeColor}">${item.type || 'Suggestion'}</span>
          </div>
          <div class="suggestion-desc">${item.detailedDescription}</div>
          
          <div class="code-preview">
            <pre><code>${this.escapeHtml(item.yamlCode)}</code></pre>
          </div>

          <div class="suggestion-actions">
            <mwc-button class="btn-decline" data-id="${item.id}">Decline (Ignore)</mwc-button>
            <mwc-button raised class="btn-accept" data-id="${item.id}">Accept</mwc-button>
          </div>
        </div>
      `;

      // Add Event Listeners for buttons
      card.querySelector('.btn-accept').addEventListener('click', () => this.handleAction('accept', item.id));
      card.querySelector('.btn-decline').addEventListener('click', () => this.handleAction('decline', item.id));

      this.content.appendChild(card);
    });
  }

  async handleAction(action, id) {
    try {
        // Call the API endpoint: /api/ai_automation_suggester/{action}/{id}
        await this._hass.callApi("POST", `ai_automation_suggester/${action}/${id}`);
        
        // Remove the item from UI instantly for snappy feel
        this.fetchSuggestions(); 
    } catch (err) {
        alert(`Error: ${err.message}`);
    }
  }

  escapeHtml(text) {
    if (!text) return "";
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  setConfig(config) {
    this.config = config;
  }

  getCardSize() {
    return 3;
  }
}

// Minimal CSS Styling
const style = document.createElement('style');
style.textContent = `
  .suggestion-item {
    background: var(--card-background-color);
    margin-bottom: 16px;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    overflow: hidden;
  }
  .suggestion-header {
    padding: 16px;
    background: rgba(var(--rgb-primary-text-color), 0.03);
  }
  .suggestion-title {
    font-size: 1.2em;
    display: flex;
    align-items: center;
    margin-bottom: 8px;
  }
  .suggestion-badge {
    font-size: 0.7em;
    color: white;
    padding: 2px 8px;
    border-radius: 12px;
    margin-left: auto;
    text-transform: uppercase;
  }
  .suggestion-desc {
    opacity: 0.8;
    margin-bottom: 12px;
  }
  .code-preview {
    background: #1c1c1c;
    color: #ddd;
    padding: 10px;
    border-radius: 4px;
    font-family: monospace;
    font-size: 0.85em;
    overflow-x: auto;
    margin-bottom: 12px;
    max-height: 150px;
  }
  .suggestion-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  .loading, .error, .no-data {
    padding: 24px;
    text-align: center;
    font-style: italic;
    color: var(--secondary-text-color);
  }
  .btn-decline {
    --mdc-theme-primary: var(--error-color);
  }
`;
document.head.appendChild(style);

customElements.define("ai-automation-suggester-card", AIAutomationSuggesterCard);
