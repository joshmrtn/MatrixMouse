/**
 * Settings Page Component
 *
 * Allows configuration of workspace and repo-level settings.
 * - Repo overrides at TOP (select repo or workspace)
 * - Workspace settings: models, git identity, server config
 */

import { getState, subscribe } from '../state';
import { escapeHtml } from '../utils';
import { getConfig, updateConfig, getRepoConfig, updateRepoConfig } from '../api';

export class SettingsPage {
  private element: HTMLElement | null = null;
  private workspaceConfig: Record<string, unknown> = {};
  private repoConfigs: Record<string, Record<string, unknown>> = {};
  private selectedRepo: string | null = null;

  constructor() {
    subscribe((state) => {
      // Could refresh config if repos change
    });
  }

  async render(container: HTMLElement): Promise<void> {
    container.innerHTML = `
      <div id="settings-page">
        <h1>Settings</h1>

        <!-- Repo Overrides at TOP -->
        <div id="repo-overrides" class="settings-section">
          <h2>Repo Overrides</h2>
          <p class="section-description">
            Select a repository to configure repo-specific settings, or select "Workspace" for global settings.
          </p>
          
          <div class="config-field">
            <label for="repo-select">Scope:</label>
            <select id="repo-select" name="repo">
              <option value="">Workspace (Global Settings)</option>
            </select>
          </div>

          <div id="repo-config-container" style="display: none;">
            <form id="repo-config-form">
              <div class="config-group">
                <h3>Repo-Specific Models</h3>
                <div class="config-field">
                  <label for="repo_coder_model">Coder Model</label>
                  <input type="text" id="repo_coder_model" name="repo_coder_model" />
                </div>
                <div class="config-field">
                  <label for="repo_manager_model">Manager Model</label>
                  <input type="text" id="repo_manager_model" name="repo_manager_model" />
                </div>
              </div>

              <div class="form-actions">
                <button type="submit" class="btn-save">Save Repo Config</button>
                <button type="button" class="btn-cancel">Cancel</button>
              </div>
            </form>
            <div class="repo-config-loaded" style="display: none;"></div>
          </div>
        </div>

        <!-- Workspace Configuration -->
        <div id="workspace-settings" class="settings-section">
          <h2>Workspace Configuration</h2>
          <form id="workspace-config-form">
            <div class="config-group">
              <h3>Models</h3>
              <div class="config-field">
                <label for="coder_model">Coder Model</label>
                <input type="text" id="coder_model" name="coder_model" placeholder="ollama:qwen3.5:4b" />
              </div>
              <div class="config-field">
                <label for="manager_model">Manager Model</label>
                <input type="text" id="manager_model" name="manager_model" placeholder="ollama:qwen3.5:9b" />
              </div>
              <div class="config-field">
                <label for="critic_model">Critic Model</label>
                <input type="text" id="critic_model" name="critic_model" placeholder="ollama:qwen3.5:9b" />
              </div>
              <div class="config-field">
                <label for="writer_model">Writer Model</label>
                <input type="text" id="writer_model" name="writer_model" placeholder="ollama:qwen3.5:4b" />
              </div>
              <div class="config-field">
                <label for="summarizer_model">Summarizer Model</label>
                <input type="text" id="summarizer_model" name="summarizer_model" placeholder="ollama:qwen3.5:2b" />
              </div>
            </div>

            <div class="config-group">
              <h3>Agent Identity</h3>
              <div class="config-field">
                <label for="agent_git_name">Git Name</label>
                <input type="text" id="agent_git_name" name="agent_git_name" placeholder="MatrixMouse Bot" />
              </div>
              <div class="config-field">
                <label for="agent_git_email">Git Email</label>
                <input type="email" id="agent_git_email" name="agent_git_email" placeholder="matrixmouse@example.com" />
              </div>
            </div>

            <div class="config-group">
              <h3>Server</h3>
              <div class="config-field">
                <label for="server_port">Server Port</label>
                <input type="number" id="server_port" name="server_port" min="1" max="65535" />
              </div>
              <div class="config-field">
                <label for="log_level">Log Level</label>
                <select id="log_level" name="log_level">
                  <option value="DEBUG">DEBUG</option>
                  <option value="INFO">INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                </select>
              </div>
            </div>

            <div class="form-actions">
              <button type="submit" class="btn-save">Save</button>
              <button type="button" class="btn-cancel">Cancel</button>
            </div>
          </form>

          <!-- Current Configuration Display - compact format -->
          <div id="config-display" class="config-list">
            <h3>Current Configuration</h3>
            <div id="config-items"></div>
          </div>
        </div>

        <div id="settings-message" class="message" style="display: none;"></div>
      </div>
    `;

    this.element = container.querySelector("#settings-page");
    await this.loadWorkspaceConfig();
    this.setupWorkspaceForm();
    this.setupRepoSelector();
    this.setupRepoForm();
  }

  private async loadWorkspaceConfig(): Promise<void> {
    try {
      this.workspaceConfig = await getConfig();
      this.populateWorkspaceForm();
      this.displayConfig();
    } catch (error) {
      this.showMessage(`Failed to load config: ${error}`, "error");
    }
  }

  private populateWorkspaceForm(): void {
    if (!this.element) return;

    const form = this.element.querySelector("#workspace-config-form") as HTMLFormElement;
    
    // Populate known fields
    const fields = [
      "coder_model", "manager_model", "critic_model",
      "writer_model", "summarizer_model",
      "agent_git_name", "agent_git_email",
      "server_port", "log_level"
    ];

    fields.forEach(field => {
      const input = form.querySelector(`[name="${field}"]`) as HTMLInputElement | HTMLSelectElement;
      if (input && this.workspaceConfig[field] !== undefined) {
        input.value = String(this.workspaceConfig[field]);
      }
    });
  }

  private displayConfig(): void {
    if (!this.element) return;

    const configItemsEl = this.element.querySelector("#config-items");
    if (!configItemsEl) return;

    // Display config in a compact, scrollable format
    configItemsEl.innerHTML = Object.entries(this.workspaceConfig)
      .map(([key, value]) => {
        const displayValue = typeof value === 'object' 
          ? JSON.stringify(value) 
          : String(value);
        return `
          <div class="config-item">
            <span class="config-key">${escapeHtml(key)}</span>
            <span class="config-value" title="${escapeHtml(displayValue)}">${escapeHtml(displayValue)}</span>
          </div>
        `;
      })
      .join('');
  }

  private setupWorkspaceForm(): void {
    if (!this.element) return;

    const form = this.element.querySelector("#workspace-config-form") as HTMLFormElement;
    const cancelButton = form.querySelector(".btn-cancel");

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await this.saveWorkspaceConfig();
    });

    cancelButton?.addEventListener("click", () => {
      this.populateWorkspaceForm();
      this.showMessage("Changes discarded", "info");
    });
  }

  private async saveWorkspaceConfig(): Promise<void> {
    if (!this.element) return;

    const form = this.element.querySelector("#workspace-config-form") as HTMLFormElement;
    const formData = new FormData(form);
    const values: Record<string, unknown> = {};

    for (const [key, value] of formData.entries()) {
      // Parse numbers
      if (key === "server_port") {
        values[key] = parseInt(value as string, 10);
      } else {
        values[key] = value;
      }
    }

    try {
      const result = await updateConfig(values);
      if (result.ok) {
        this.showMessage("Settings saved successfully", "success");
        this.workspaceConfig = { ...this.workspaceConfig, ...values };
        this.displayConfig();
      }
    } catch (error) {
      this.showMessage(`Failed to save: ${error}`, "error");
    }
  }

  private setupRepoSelector(): void {
    if (!this.element) return;

    const select = this.element.querySelector("#repo-select") as HTMLSelectElement;
    if (!select) return;

    // Populate repos from state
    const { repos } = getState();
    repos.forEach(repo => {
      const option = document.createElement("option");
      option.value = repo.name;
      option.textContent = repo.name;
      select.appendChild(option);
    });

    select.addEventListener("change", async () => {
      this.selectedRepo = select.value || null;
      if (this.selectedRepo) {
        await this.loadRepoConfig(this.selectedRepo);
      } else {
        this.hideRepoConfig();
      }
    });
  }

  private async loadRepoConfig(repoName: string): Promise<void> {
    if (!this.element) return;

    try {
      const config = await getRepoConfig(repoName);
      this.repoConfigs[repoName] = config.merged || {};
      this.showRepoConfig();
      this.populateRepoForm();
    } catch (error) {
      this.showMessage(`Failed to load repo config: ${error}`, "error");
    }
  }

  private showRepoConfig(): void {
    if (!this.element) return;

    const container = this.element.querySelector("#repo-config-container");
    if (container) {
      container.style.display = "block";
    }
  }

  private hideRepoConfig(): void {
    if (!this.element) return;

    const container = this.element.querySelector("#repo-config-container");
    if (container) {
      container.style.display = "none";
    }
  }

  private populateRepoForm(): void {
    if (!this.element || !this.selectedRepo) return;

    const form = this.element.querySelector("#repo-config-form") as HTMLFormElement;
    const config = this.repoConfigs[this.selectedRepo] || {};

    ["repo_coder_model", "repo_manager_model"].forEach(field => {
      const input = form.querySelector(`[name="${field}"]`) as HTMLInputElement;
      const configKey = field.replace("repo_", "");
      if (input && config[configKey] !== undefined) {
        input.value = String(config[configKey]);
      }
    });
  }

  private setupRepoForm(): void {
    if (!this.element) return;

    const form = this.element.querySelector("#repo-config-form") as HTMLFormElement;
    const cancelButton = form.querySelector(".btn-cancel");

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await this.saveRepoConfig();
    });

    cancelButton?.addEventListener("click", () => {
      if (this.selectedRepo) {
        this.populateRepoForm();
      }
    });
  }

  private async saveRepoConfig(): Promise<void> {
    if (!this.element || !this.selectedRepo) return;

    const form = this.element.querySelector("#repo-config-form") as HTMLFormElement;
    const formData = new FormData(form);
    const values: Record<string, unknown> = {};

    for (const [key, value] of formData.entries()) {
      values[key.replace("repo_", "")] = value;
    }

    try {
      const result = await updateRepoConfig(this.selectedRepo, values, false);
      if (result.ok) {
        this.showMessage(`Repo config saved for ${this.selectedRepo}`, "success");
        const loadedEl = this.element.querySelector(".repo-config-loaded");
        if (loadedEl) {
          loadedEl.textContent = "Configuration saved!";
          loadedEl.style.display = "block";
          setTimeout(() => {
            if (loadedEl) loadedEl.style.display = "none";
          }, 3000);
        }
      }
    } catch (error) {
      this.showMessage(`Failed to save repo config: ${error}`, "error");
    }
  }

  private showMessage(text: string, type: "success" | "error" | "info"): void {
    if (!this.element) return;

    const messageEl = this.element.querySelector("#settings-message") as HTMLElement;
    if (messageEl) {
      messageEl.textContent = text;
      messageEl.className = `message ${type}`;
      messageEl.style.display = "block";

      // Auto-hide after 5 seconds
      setTimeout(() => {
        messageEl.style.display = "none";
      }, 5000);
    }
  }
}
