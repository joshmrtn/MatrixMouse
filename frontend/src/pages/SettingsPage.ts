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
import { formatApiError } from '../utils/errorFormatting';

type Scope = 'workspace' | 'repo';

const MODEL_FIELDS = [
  'coder_model', 'manager_model', 'critic_model',
  'writer_model', 'summarizer_model',
] as const;

const WORKSPACE_FIELDS = [
  ...MODEL_FIELDS,
  'agent_git_name', 'agent_git_email',
  'server_port', 'log_level',
] as const;

export class SettingsPage {
  private element: HTMLElement | null = null;
  private workspaceConfig: Record<string, unknown> = {};
  private repoConfigs: Record<string, Record<string, unknown>> = {};
  private selectedRepo: string | null = null;
  private originalWorkspaceConfig: Record<string, unknown> = {};
  private originalRepoConfig: Record<string, unknown> = {};
  private isSavingWorkspace = false;
  private isSavingRepo = false;
  private isRefreshing = false;
  private isDestroyed = false;
  private unsubscribeState: (() => void) | null = null;
  private lastRepoList: string[] = [];

  constructor() {
    this.unsubscribeState = subscribe((state) => {
      if (!this.element) return;
      const currentRepoNames = state.repos.map(r => r.name);
      if (this.reposChanged(currentRepoNames)) {
        this.lastRepoList = currentRepoNames;
        this.setupRepoSelector();
      }
    });
  }

  /**
   * Cleanup method to be called when navigating away from SettingsPage
   */
  public destroy(): void {
    this.isDestroyed = true;
    if (this.unsubscribeState) {
      this.unsubscribeState();
      this.unsubscribeState = null;
    }
    this.lastRepoList = [];
    this.selectedRepo = null;
    this.workspaceConfig = {};
    this.repoConfigs = {};
    this.originalWorkspaceConfig = {};
    this.originalRepoConfig = {};
    this.element = null;
  }

  private reposChanged(current: string[]): boolean {
    if (current.length !== this.lastRepoList.length) return true;
    return current.some((name, i) => name !== this.lastRepoList[i]);
  }

  /**
   * Validate model fields (allow empty for repo overrides)
   */
  private validateModelFields(values: Record<string, unknown>, errors: Record<string, string>, allowEmpty = false): void {
    for (const field of MODEL_FIELDS) {
      if (values[field] !== undefined) {
        const value = String(values[field]);
        if (!allowEmpty && !value.trim()) {
          errors[field] = 'Model cannot be empty';
        } else if (value.trim().length > 0 && value.trim().length < 3) {
          errors[field] = 'Model name too short';
        }
      }
    }
  }

  /**
   * Validate workspace config values
   */
  private validateWorkspaceConfig(values: Record<string, unknown>): { valid: boolean; errors: Record<string, string> } {
    const errors: Record<string, string> = {};

    if (values.server_port !== undefined) {
      const port = Number(values.server_port);
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        errors.server_port = 'Port must be an integer between 1 and 65535';
      }
    }

    if (values.agent_git_email !== undefined) {
      const email = String(values.agent_git_email);
      const emailRegex = /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;
      if (!emailRegex.test(email)) {
        errors.agent_git_email = 'Invalid email format';
      }
    }

    this.validateModelFields(values, errors);
    return { valid: Object.keys(errors).length === 0, errors };
  }

  /**
   * Validate repo config values (allow empty models)
   */
  private validateRepoConfig(values: Record<string, unknown>): { valid: boolean; errors: Record<string, string> } {
    const errors: Record<string, string> = {};
    this.validateModelFields(values, errors, true);
    return { valid: Object.keys(errors).length === 0, errors };
  }

  /**
   * Display validation errors inline
   */
  private showValidationErrors(form: HTMLFormElement, errors: Record<string, string>): void {
    form.querySelectorAll('.field-error').forEach((el) => el.remove());
    form.querySelectorAll('.input-error').forEach((el) => el.classList.remove('input-error'));

    let firstInput: HTMLElement | null = null;
    for (const [field, message] of Object.entries(errors)) {
      const input = form.querySelector(`[name="${field}"]`);
      if (input) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'field-error';
        errorDiv.textContent = message;
        input.classList.add('input-error');
        input.parentNode?.appendChild(errorDiv);
        if (!firstInput) firstInput = input as HTMLElement;
      }
    }

    if (firstInput && typeof firstInput.scrollIntoView === 'function') {
      firstInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  /**
   * Show a message (no auto-hide, no retry button)
   */
  private showMessage(text: string, type: 'success' | 'error' | 'info'): void {
    if (!this.element) return;
    const messageEl = this.element.querySelector('#settings-message') as HTMLElement;
    if (messageEl) {
      messageEl.textContent = text;
      messageEl.className = `message ${type}`;
      messageEl.style.display = 'block';
    }
  }

  /**
   * Hide the message
   */
  private hideMessage(): void {
    if (!this.element) return;
    const messageEl = this.element.querySelector('#settings-message') as HTMLElement;
    if (messageEl) {
      messageEl.textContent = '';
      messageEl.style.display = 'none';
    }
  }

  /**
   * Enable or disable all form inputs
   */
  private setFormDisabled(disabled: boolean): void {
    if (!this.element) return;
    const forms = this.element.querySelectorAll('form');
    forms.forEach(form => {
      const inputs = form.querySelectorAll('input, select, button[type="submit"]');
      inputs.forEach(input => {
        (input as HTMLInputElement | HTMLSelectElement | HTMLButtonElement).disabled = disabled;
      });
    });
    const refreshBtn = this.element.querySelector('.refresh-config-btn') as HTMLButtonElement;
    if (refreshBtn) refreshBtn.disabled = disabled;
  }

  /**
   * Update save button state (loading/disabled)
   */
  private updateSaveButtonState(type: Scope): void {
    if (!this.element) return;
    const formId = type === 'workspace' ? '#workspace-config-form' : '#repo-config-form';
    const saveButton = this.element.querySelector(`${formId} .btn-save`) as HTMLButtonElement;
    if (!saveButton) return;
    const isSaving = type === 'workspace' ? this.isSavingWorkspace : this.isSavingRepo;
    saveButton.disabled = isSaving;
    saveButton.textContent = isSaving ? 'Saving...' : (type === 'workspace' ? 'Save' : 'Save Repo Config');
  }

  /**
   * Show/hide repo config container
   */
  private setRepoConfigVisible(visible: boolean): void {
    if (!this.element) return;
    const container = this.element.querySelector('#repo-config-container') as HTMLElement;
    if (container) container.style.display = visible ? 'block' : 'none';
  }

  // ---------------------------------------------------------------------------
  // Load / Populate / Validate / Save — parameterized by scope
  // ---------------------------------------------------------------------------

  private async loadConfig(scope: Scope, repoName?: string): Promise<void> {
    if (!this.element) return;
    this.setFormDisabled(true);
    try {
      if (scope === 'workspace') {
        this.workspaceConfig = await getConfig();
        if (this.isDestroyed) return;
        this.populateForm('workspace');
      } else if (repoName) {
        const config = await getRepoConfig(repoName);
        if (this.isDestroyed) return;
        this.repoConfigs[repoName] = config.merged || {};
        this.setRepoConfigVisible(true);
        this.populateForm('repo');
      }
    } catch (error) {
      const errorMessage = formatApiError(error);
      this.showMessage(`Failed to load config: ${errorMessage}`, 'error');
    } finally {
      this.setFormDisabled(false);
    }
  }

  private populateForm(scope: Scope): void {
    if (!this.element) return;

    const config = scope === 'workspace'
      ? this.workspaceConfig
      : (this.selectedRepo ? this.repoConfigs[this.selectedRepo] || {} : {});

    const formId = scope === 'workspace' ? '#workspace-config-form' : '#repo-config-form';
    const form = this.element.querySelector(formId) as HTMLFormElement;
    if (!form) return;

    // Save original config for diff detection on save
    if (scope === 'workspace') {
      this.originalWorkspaceConfig = { ...config };
    } else {
      this.originalRepoConfig = { ...config };
    }

    // Clear any validation errors
    form.querySelectorAll('.field-error').forEach((el) => el.remove());
    form.querySelectorAll('.input-error').forEach((el) => el.classList.remove('input-error'));

    const fields = scope === 'workspace' ? WORKSPACE_FIELDS : MODEL_FIELDS;
    for (const field of fields) {
      const inputName = scope === 'workspace' ? field : `repo_${field}`;
      const input = form.querySelector(`[name="${inputName}"]`) as HTMLInputElement | HTMLSelectElement;
      if (input && config[field] !== undefined) {
        input.value = String(config[field]);
      }
    }

    this.hideMessage();
  }

  private validateForm(scope: Scope, values: Record<string, unknown>): { valid: boolean; errors: Record<string, string> } {
    return scope === 'workspace'
      ? this.validateWorkspaceConfig(values)
      : this.validateRepoConfig(values);
  }

  private async saveConfig(scope: Scope): Promise<void> {
    if (!this.element) return;

    const formId = scope === 'workspace' ? '#workspace-config-form' : '#repo-config-form';
    const form = this.element.querySelector(formId) as HTMLFormElement;
    const formData = new FormData(form);

    const values: Record<string, unknown> = {};
    formData.forEach((value, key) => {
      const actualKey = key.replace('repo_', '');
      values[actualKey] = actualKey === 'server_port' ? parseInt(value as string, 10) : value;
    });

    // Validate
    const validation = this.validateForm(scope, values);
    if (!validation.valid) {
      this.showValidationErrors(form, validation.errors);
      this.showMessage('Please fix validation errors', 'error');
      return;
    }

    // Get changed values
    const original = scope === 'workspace' ? this.originalWorkspaceConfig : this.originalRepoConfig;
    const changes: Record<string, unknown> = {};
    for (const [key, value] of formData) {
      const actualKey = key.replace('repo_', '');
      const originalValue = original[actualKey];
      let parsedValue: unknown = value;
      if (typeof originalValue === 'number') {
        const num = Number(value);
        parsedValue = Number.isNaN(num) ? value : num;
      }
      if (!(actualKey in original) || originalValue !== parsedValue) {
        if (typeof parsedValue === 'string' && parsedValue.trim() === '') continue;
        changes[actualKey] = parsedValue;
      }
    }

    if (Object.keys(changes).length === 0) {
      this.showMessage('No changes to save', 'info');
      return;
    }

    // Set loading state
    if (scope === 'workspace') {
      this.isSavingWorkspace = true;
    } else {
      this.isSavingRepo = true;
    }
    this.updateSaveButtonState(scope);

    try {
      let result: { ok: boolean };
      if (scope === 'workspace') {
        result = await updateConfig(changes);
      } else if (this.selectedRepo) {
        result = await updateRepoConfig(this.selectedRepo, changes, false);
      } else {
        return;
      }

      if (this.isDestroyed) return;

      if (result.ok) {
        if (scope === 'workspace') {
          this.workspaceConfig = { ...this.workspaceConfig, ...changes };
          this.originalWorkspaceConfig = { ...this.originalWorkspaceConfig, ...changes };
          this.showMessage('Settings saved successfully', 'success');
        } else {
          this.originalRepoConfig = { ...this.originalRepoConfig, ...changes };
          this.showMessage(`Repo config saved for ${this.selectedRepo}`, 'success');
        }
      } else {
        this.showMessage('Failed to save settings. Please try again.', 'error');
      }
    } catch (error) {
      const errorMessage = formatApiError(error);
      this.showMessage(errorMessage, 'error');
    } finally {
      if (scope === 'workspace') {
        this.isSavingWorkspace = false;
      } else {
        this.isSavingRepo = false;
      }
      this.updateSaveButtonState(scope);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  async render(container: HTMLElement): Promise<void> {
    if (this.element) {
      this.destroy();
    }

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
                <div class="config-field">
                  <label for="repo_critic_model">Critic Model</label>
                  <input type="text" id="repo_critic_model" name="repo_critic_model" />
                </div>
                <div class="config-field">
                  <label for="repo_writer_model">Writer Model</label>
                  <input type="text" id="repo_writer_model" name="repo_writer_model" />
                </div>
                <div class="config-field">
                  <label for="repo_summarizer_model">Summarizer Model</label>
                  <input type="text" id="repo_summarizer_model" name="repo_summarizer_model" />
                </div>
              </div>

              <div class="form-actions">
                <button type="submit" class="btn-save" aria-label="Save repo configuration">Save Repo Config</button>
                <button type="button" class="btn-cancel">Cancel</button>
              </div>
            </form>
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
                <input type="text" id="coder_model" name="coder_model" placeholder="ollama:qwen3.5:4b" aria-label="Coder Model" />
              </div>
              <div class="config-field">
                <label for="manager_model">Manager Model</label>
                <input type="text" id="manager_model" name="manager_model" placeholder="ollama:qwen3.5:9b" aria-label="Manager Model" />
              </div>
              <div class="config-field">
                <label for="critic_model">Critic Model</label>
                <input type="text" id="critic_model" name="critic_model" placeholder="ollama:qwen3.5:9b" aria-label="Critic Model" />
              </div>
              <div class="config-field">
                <label for="writer_model">Writer Model</label>
                <input type="text" id="writer_model" name="writer_model" placeholder="ollama:qwen3.5:4b" aria-label="Writer Model" />
              </div>
              <div class="config-field">
                <label for="summarizer_model">Summarizer Model</label>
                <input type="text" id="summarizer_model" name="summarizer_model" placeholder="ollama:qwen3.5:2b" aria-label="Summarizer Model" />
              </div>
            </div>

            <div class="config-group">
              <h3>Agent Identity</h3>
              <div class="config-field">
                <label for="agent_git_name">Git Name</label>
                <input type="text" id="agent_git_name" name="agent_git_name" placeholder="MatrixMouse Bot" aria-label="Git Name" />
              </div>
              <div class="config-field">
                <label for="agent_git_email">Git Email</label>
                <input type="email" id="agent_git_email" name="agent_git_email" placeholder="matrixmouse@example.com" aria-label="Git Email" />
              </div>
            </div>

            <div class="config-group">
              <h3>Server</h3>
              <div class="config-field">
                <label for="server_port">Server Port</label>
                <input type="number" id="server_port" name="server_port" min="1" max="65535" aria-label="Server Port" />
              </div>
              <div class="config-field">
                <label for="log_level">Log Level</label>
                <select id="log_level" name="log_level" aria-label="Log Level">
                  <option value="DEBUG">DEBUG</option>
                  <option value="INFO">INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                </select>
              </div>
            </div>

            <div class="form-actions">
              <button type="submit" class="btn-save" aria-label="Save workspace configuration">Save</button>
              <button type="button" class="btn-cancel">Cancel</button>
            </div>
          </form>
        </div>

        <div id="settings-message" class="message" style="display: none;" role="alert" aria-live="assertive"></div>

        <div class="refresh-actions">
          <button type="button" class="refresh-config-btn" aria-label="Refresh configuration">
            &#x27f3; Refresh
          </button>
        </div>
      </div>
    `;

    this.element = container.querySelector('#settings-page');
    await this.loadConfig('workspace');
    this.setupRepoSelector();
    this.setupRepoForm();
    this.setupWorkspaceForm();
    this.setupRefreshButton();
  }

  // ---------------------------------------------------------------------------
  // Form setup helpers
  // ---------------------------------------------------------------------------

  private setupWorkspaceForm(): void {
    if (!this.element) return;
    const form = this.element.querySelector('#workspace-config-form') as HTMLFormElement;
    if (!form) return;

    const cancelButton = form.querySelector('.btn-cancel');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.saveConfig('workspace');
    });
    cancelButton?.addEventListener('click', () => {
      this.populateForm('workspace');
      this.showMessage('Changes discarded', 'info');
    });
  }

  private setupRepoForm(): void {
    if (!this.element) return;
    const form = this.element.querySelector('#repo-config-form') as HTMLFormElement;
    if (!form) return;

    const cancelButton = form.querySelector('.btn-cancel');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.saveConfig('repo');
    });
    cancelButton?.addEventListener('click', () => {
      if (this.selectedRepo) {
        this.populateForm('repo');
        this.showMessage('Repo changes discarded', 'info');
      }
    });
  }

  /**
   * Setup repo selector dropdown
   */
  private setupRepoSelector(): void {
    if (!this.element) return;

    const select = this.element.querySelector('#repo-select') as HTMLSelectElement;
    if (!select) return;

    select.innerHTML = '<option value="">Workspace (Global Settings)</option>';
    const { repos } = getState();
    const repoNames = new Set<string>();
    repos.forEach(repo => {
      repoNames.add(repo.name);
      const option = document.createElement('option');
      option.value = repo.name;
      option.textContent = repo.name;
      select.appendChild(option);
    });

    // Check if currently selected repo still exists, reset if not
    if (this.selectedRepo && !repoNames.has(this.selectedRepo)) {
      this.selectedRepo = null;
      this.setRepoConfigVisible(false);
    } else if (this.selectedRepo) {
      select.value = this.selectedRepo;
    }

    select.addEventListener('change', async () => {
      this.selectedRepo = select.value || null;
      if (this.selectedRepo) {
        await this.loadConfig('repo', this.selectedRepo);
      } else {
        this.setRepoConfigVisible(false);
      }
    });
  }

  /**
   * Setup refresh button
   */
  private setupRefreshButton(): void {
    if (!this.element) return;
    const refreshBtn = this.element.querySelector('.refresh-config-btn') as HTMLButtonElement;
    if (!refreshBtn) return;
    refreshBtn.addEventListener('click', () => this.refreshConfig());
  }

  /**
   * Refresh configuration from server
   */
  private async refreshConfig(): Promise<void> {
    if (!this.element) return;
    if (this.isRefreshing) return;
    this.isRefreshing = true;

    try {
      if (this.isSavingWorkspace || this.isSavingRepo) {
        this.showMessage('Cannot refresh while saving. Please wait.', 'info');
        return;
      }

      const refreshBtn = this.element.querySelector('.refresh-config-btn') as HTMLButtonElement;
      if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = '\u27f3 Refreshing...';
      }

      await this.loadConfig('workspace');
      if (this.isDestroyed) return;

      if (this.selectedRepo) {
        await this.loadConfig('repo', this.selectedRepo);
      }

      this.showMessage('Configuration refreshed', 'success');
    } catch (error) {
      const errorMessage = formatApiError(error);
      this.showMessage(`Failed to refresh: ${errorMessage}`, 'error');
    } finally {
      this.isRefreshing = false;
      if (this.element) {
        const refreshBtn = this.element.querySelector('.refresh-config-btn') as HTMLButtonElement;
        if (refreshBtn) {
          refreshBtn.disabled = false;
          refreshBtn.textContent = '\u27f3 Refresh';
        }
      }
    }
  }
}
