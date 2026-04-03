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

export class SettingsPage {
  private element: HTMLElement | null = null;
  private workspaceConfig: Record<string, unknown> = {};
  private repoConfigs: Record<string, Record<string, unknown>> = {};
  private selectedRepo: string | null = null;
  private originalWorkspaceConfig: Record<string, unknown> = {};
  private originalRepoConfig: Record<string, unknown> = {};
  private isSavingWorkspace: boolean = false;
  private isSavingRepo: boolean = false;
  private isRefreshing: boolean = false;
  private isLoadingConfig: boolean = false;
  private isDestroyed: boolean = false;
  private workspaceDirty: boolean = false;
  private repoDirty: boolean = false;
  private beforeUnloadHandler: ((e: BeforeUnloadEvent) => void) | null = null;
  private unsubscribeState: (() => void) | null = null;
  private keyboardShortcutHandler: ((e: KeyboardEvent) => void) | null = null;
  private lastRepoList: string[] = [];
  private workspaceDebounceTimer: number | null = null;
  private repoDebounceTimer: number | null = null;
  private messageAutoHideTimer: number | null = null;
  private lastConfigCount: number = 0;

  // Constants for field lists
  private static readonly MODEL_FIELDS = [
    'coder_model', 'manager_model', 'critic_model',
    'writer_model', 'summarizer_model'
  ];

  // Field lists for form population and validation
  private static readonly WORKSPACE_FIELDS = [
    'coder_model', 'manager_model', 'critic_model',
    'writer_model', 'summarizer_model',
    'agent_git_name', 'agent_git_email',
    'server_port', 'log_level'
  ];

  // Repo overrides only include model fields
  private static readonly REPO_FIELDS = SettingsPage.MODEL_FIELDS;

  private static readonly CONFIG_VALUE_MAX_LENGTH = 50;

  /**
   * Check if repo list has changed
   */
  private reposChanged(current: string[]): boolean {
    if (current.length !== this.lastRepoList.length) return true;
    return current.some((name, i) => name !== this.lastRepoList[i]);
  }

  constructor() {
    this.unsubscribeState = subscribe((state) => {
      // Only refresh repo selector when repos actually change
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
    // Mark as destroyed to prevent stale async updates
    this.isDestroyed = true;

    this.cleanupBeforeUnload();

    if (this.keyboardShortcutHandler) {
      document.removeEventListener('keydown', this.keyboardShortcutHandler);
      this.keyboardShortcutHandler = null;
    }

    if (this.unsubscribeState) {
      this.unsubscribeState();
      this.unsubscribeState = null;
    }

    // Clear debounce timers
    if (this.workspaceDebounceTimer) {
      window.clearTimeout(this.workspaceDebounceTimer);
      this.workspaceDebounceTimer = null;
    }
    if (this.repoDebounceTimer) {
      window.clearTimeout(this.repoDebounceTimer);
      this.repoDebounceTimer = null;
    }

    // Reset state
    this.workspaceDirty = false;
    this.repoDirty = false;
    this.lastRepoList = [];
    this.selectedRepo = null;
    this.workspaceConfig = {};
    this.repoConfigs = {};
    this.originalWorkspaceConfig = {};
    this.originalRepoConfig = {};
    this.element = null;
  }

  /**
   * Check if there are unsaved changes
   */
  hasUnsavedChanges(type: 'workspace' | 'repo' | 'any' = 'any'): boolean {
    if (type === 'workspace') return this.workspaceDirty;
    if (type === 'repo') return this.repoDirty;
    return this.workspaceDirty || this.repoDirty;
  }

  /**
   * Update dirty state and UI indicators
   */
  private setDirty(type: 'workspace' | 'repo', isDirty: boolean): void {
    if (type === 'workspace') {
      this.workspaceDirty = isDirty;
    } else {
      this.repoDirty = isDirty;
    }

    this.updateUnsavedChangesIndicator();
    this.updateBeforeUnloadHandler();
  }

  /**
   * Update unsaved changes indicator visibility
   */
  private updateUnsavedChangesIndicator(): void {
    if (!this.element) return;

    const indicator = this.element.querySelector('.unsaved-changes-indicator') as HTMLElement;
    if (indicator) {
      indicator.style.display = this.hasUnsavedChanges() ? 'block' : 'none';
    }
  }

  /**
   * Register/unregister beforeunload handler
   */
  private updateBeforeUnloadHandler(): void {
    if (this.hasUnsavedChanges()) {
      if (!this.beforeUnloadHandler) {
        this.beforeUnloadHandler = (e: BeforeUnloadEvent) => {
          e.preventDefault();
          e.returnValue = '';
          return '';
        };
        window.addEventListener('beforeunload', this.beforeUnloadHandler);
      }
    } else {
      if (this.beforeUnloadHandler) {
        window.removeEventListener('beforeunload', this.beforeUnloadHandler);
        this.beforeUnloadHandler = null;
      }
    }
  }

  /**
   * Cleanup beforeunload handler on page destroy
   */
  private cleanupBeforeUnload(): void {
    if (this.beforeUnloadHandler) {
      window.removeEventListener('beforeunload', this.beforeUnloadHandler);
      this.beforeUnloadHandler = null;
    }
  }

  /**
   * Validate model fields are not empty
   * @param values - The form values to validate
   * @param errors - The errors object to populate
   * @param allowEmpty - If true, allow empty values (for repo overrides)
   */
  private validateModelFields(values: Record<string, unknown>, errors: Record<string, string>, allowEmpty: boolean = false): void {
    for (const field of SettingsPage.MODEL_FIELDS) {
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

    // Validate server_port (1-65535, integer only)
    if (values.server_port !== undefined) {
      const port = Number(values.server_port);
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        errors.server_port = 'Port must be an integer between 1 and 65535';
      }
    }

    // Validate agent_git_email format
    if (values.agent_git_email !== undefined) {
      const email = String(values.agent_git_email);
      // More robust email regex supporting subdomains and common TLDs
      const emailRegex = /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;
      if (!emailRegex.test(email)) {
        errors.agent_git_email = 'Invalid email format';
      }
    }

    // Validate model fields are not empty
    this.validateModelFields(values, errors);

    return { valid: Object.keys(errors).length === 0, errors };
  }

  /**
   * Validate repo config values
   */
  private validateRepoConfig(values: Record<string, unknown>): { valid: boolean; errors: Record<string, string> } {
    const errors: Record<string, string> = {};

    // Validate model fields (allow empty values for repo overrides)
    this.validateModelFields(values, errors, true);

    return { valid: Object.keys(errors).length === 0, errors };
  }

  /**
   * Display validation errors inline
   */
  private showValidationErrors(form: HTMLFormElement, errors: Record<string, string>): void {
    // Clear previous errors
    form.querySelectorAll('.field-error').forEach((el) => el.remove());
    form.querySelectorAll('.input-error').forEach((el) => el.classList.remove('input-error'));

    const errorFields = Object.keys(errors);
    let firstInput: HTMLElement | null = null;

    // Add error messages below invalid fields
    for (const [field, message] of Object.entries(errors)) {
      const input = form.querySelector(`[name="${field}"]`);
      if (input) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'field-error';
        errorDiv.textContent = message;
        input.classList.add('input-error');
        input.parentNode?.appendChild(errorDiv);

        // Track first error input for scrolling
        if (!firstInput) {
          firstInput = input as HTMLElement;
        }
      }
    }

    // Scroll to first error (if supported)
    if (firstInput && typeof firstInput.scrollIntoView === 'function') {
      firstInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  /**
   * Get only changed values from form
   */
  private getChangedValues(formData: FormData, original: Record<string, unknown>): Record<string, unknown> {
    const changes: Record<string, unknown> = {};

    for (const [key, value] of formData) {
      const actualKey = key.replace('repo_', '');
      const originalValue = original[actualKey];

      // Parse based on original type
      let parsedValue: unknown = value;
      if (typeof originalValue === 'number') {
        const num = Number(value);
        parsedValue = Number.isNaN(num) ? value : num;
      } else if (typeof originalValue === 'boolean') {
        parsedValue = value === 'true' || value === 'on';
      }
      // Strings remain as-is

      // Only include if changed (use strict comparison)
      if (!(actualKey in original)) {
        // Skip empty new fields (don't send empty strings for unset fields)
        if (typeof parsedValue === 'string' && parsedValue.trim() === '') {
          continue; // Skip this field
        }
        changes[actualKey] = parsedValue;
      } else if (originalValue !== parsedValue) {
        changes[actualKey] = parsedValue;
      }
    }

    return changes;
  }

  async render(container: HTMLElement): Promise<void> {
    // Cleanup previous render if exists to prevent listener accumulation
    if (this.element) {
      this.destroy();
    }

    container.innerHTML = `
      <div id="settings-page">
        <h1>Settings</h1>
        <div class="keyboard-shortcut-hint" aria-hidden="true">
          <kbd>Ctrl+S</kbd> Save &nbsp;•&nbsp; <kbd>Esc</kbd> Cancel
        </div>
        <span class="visually-hidden">Keyboard shortcuts: Control S to save, Escape to cancel</span>
        <div class="unsaved-changes-indicator" style="display: none;" role="status" aria-live="polite">⚠ Unsaved changes</div>

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

          <!-- Current Configuration Display - compact format -->
          <div id="config-display" class="config-list">
            <h3>Current Configuration</h3>
            <div id="config-items"></div>
          </div>
        </div>

        <div id="settings-message" class="message" style="display: none;" role="status" aria-live="polite"></div>
        
        <div class="refresh-actions">
          <button type="button" class="refresh-config-btn" aria-label="Refresh configuration">
            ⟳ Refresh
          </button>
        </div>
      </div>
    `;

    this.element = container.querySelector("#settings-page");
    await this.loadWorkspaceConfig();
    this.setupWorkspaceForm();
    this.setupRepoSelector();
    this.setupRepoForm();
    this.setupKeyboardShortcuts();
    this.setupRefreshButton();
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

    // Prevent concurrent refresh operations - set flag FIRST
    if (this.isRefreshing) return;
    this.isRefreshing = true;

    try {
      // Prevent refresh during save operations
      if (this.isSavingWorkspace || this.isSavingRepo) {
        this.showMessage("Cannot refresh while saving. Please wait.", "info");
        return;
      }

      // Warn about unsaved changes
      if (this.hasUnsavedChanges()) {
        const confirmed = confirm("You have unsaved changes. Refresh will discard them. Continue?");
        if (!confirmed) return;
      }

      const refreshBtn = this.element.querySelector('.refresh-config-btn') as HTMLButtonElement;

      // Update loading state
      if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = '⟳ Refreshing...';
      }

      // Reload workspace config
      this.workspaceConfig = await getConfig();
      // Check if destroyed while waiting for API response
      if (this.isDestroyed) return;
      this.populateWorkspaceForm();
      this.displayConfig();

      // Reload selected repo config if any
      if (this.selectedRepo) {
        const config = await getRepoConfig(this.selectedRepo);
        // Check if destroyed while waiting for API response
        if (this.isDestroyed) return;
        this.repoConfigs[this.selectedRepo] = config.merged || {};
        this.populateRepoForm();
      }

      // Reset dirty state since we just loaded fresh config
      this.setDirty('workspace', false);
      this.setDirty('repo', false);

      this.showMessage("Configuration refreshed", "success");
    } catch (error) {
      const errorMessage = formatApiError(error);
      this.showMessage(`Failed to refresh: ${errorMessage}`, "error");
    } finally {
      this.isRefreshing = false;
      if (this.element) {
        const refreshBtn = this.element.querySelector('.refresh-config-btn') as HTMLButtonElement;
        if (refreshBtn) {
          refreshBtn.disabled = false;
          refreshBtn.textContent = '⟳ Refresh';
        }
      }
    }
  }

  /**
   * Setup keyboard shortcuts (Ctrl+S to save, Esc to cancel)
   */
  private setupKeyboardShortcuts(): void {
    this.keyboardShortcutHandler = (e: KeyboardEvent) => {
      // Only handle shortcuts when focused on settings page
      if (!this.element?.contains(document.activeElement)) return;

      // Ctrl+S to save
      if (e.key === 's' && e.ctrlKey) {
        e.preventDefault();

        // Save workspace or repo config depending on focus
        const repoForm = this.element.querySelector('#repo-config-form');
        const workspaceForm = this.element.querySelector('#workspace-config-form');

        if (repoForm?.contains(document.activeElement) && this.selectedRepo) {
          this.saveRepoConfig();
        } else if (workspaceForm?.contains(document.activeElement)) {
          this.saveWorkspaceConfig();
        }
      }

      // Escape to cancel - only reset the form that has focus
      if (e.key === 'Escape') {
        e.preventDefault();
        
        const repoForm = this.element.querySelector('#repo-config-form');
        const workspaceForm = this.element.querySelector('#workspace-config-form');
        
        if (repoForm?.contains(document.activeElement) && this.selectedRepo) {
          this.populateRepoForm();
          this.setDirty('repo', false);
          this.showMessage("Repo changes discarded", "info");
        } else if (workspaceForm?.contains(document.activeElement)) {
          this.populateWorkspaceForm();
          this.setDirty('workspace', false);
          this.showMessage("Workspace changes discarded", "info");
        }
      }
    };
    
    document.addEventListener('keydown', this.keyboardShortcutHandler);
  }

  private async loadWorkspaceConfig(): Promise<void> {
    if (!this.element) return;

    // Show loading state
    this.isLoadingConfig = true;
    this.setFormDisabled(true);

    try {
      this.workspaceConfig = await getConfig();
      // Check if destroyed while waiting for API response
      if (this.isDestroyed) return;
      this.populateWorkspaceForm();
      this.displayConfig();
    } catch (error) {
      const errorMessage = formatApiError(error);
      this.showMessage(`Failed to load config: ${errorMessage}`, "error");
    } finally {
      this.isLoadingConfig = false;
      this.setFormDisabled(false);
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

    // Also disable refresh button
    const refreshBtn = this.element.querySelector('.refresh-config-btn') as HTMLButtonElement;
    if (refreshBtn) {
      refreshBtn.disabled = disabled;
    }
  }

  private populateWorkspaceForm(): void {
    if (!this.element) return;

    const form = this.element.querySelector("#workspace-config-form") as HTMLFormElement;

    // Save original config for change detection
    this.originalWorkspaceConfig = { ...this.workspaceConfig };

    // Clear any validation errors
    form.querySelectorAll('.field-error').forEach((el) => el.remove());
    form.querySelectorAll('.input-error').forEach((el) => el.classList.remove('input-error'));

    // Populate known fields using constant
    SettingsPage.WORKSPACE_FIELDS.forEach(field => {
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

    // Clear existing content
    configItemsEl.innerHTML = '';

    // Display config using DOM APIs for safe XSS prevention
    Object.entries(this.workspaceConfig).forEach(([key, value]) => {
      let displayValue: string;
      let titleValue: string;

      if (typeof value === 'object' && value !== null) {
        // Pretty print arrays and objects (e.g., coder_cascade)
        displayValue = JSON.stringify(value, null, 2);
        titleValue = displayValue;
      } else {
        displayValue = typeof value === 'string' ? value : String(value);
        titleValue = displayValue;
      }

      // Truncate long values for display
      const truncatedDisplay = displayValue.length > SettingsPage.CONFIG_VALUE_MAX_LENGTH
        ? displayValue.substring(0, SettingsPage.CONFIG_VALUE_MAX_LENGTH) + '...'
        : displayValue;

      const item = document.createElement('div');
      item.className = 'config-item';
      item.title = titleValue;

      const keySpan = document.createElement('span');
      keySpan.className = 'config-key';
      keySpan.textContent = key;

      const valueSpan = document.createElement('span');
      valueSpan.className = 'config-value';
      valueSpan.textContent = truncatedDisplay;

      item.appendChild(keySpan);
      item.appendChild(valueSpan);
      configItemsEl.appendChild(item);
    });

    // Notify screen readers that config has been updated (only if count changed)
    const configCount = Object.keys(this.workspaceConfig).length;
    if (configCount !== this.lastConfigCount) {
      const configDisplay = this.element.querySelector('#config-display');
      if (configDisplay) {
        configDisplay.setAttribute('aria-label', `Configuration loaded with ${configCount} settings`);
      }
      this.lastConfigCount = configCount;
    }
  }

  /**
   * Setup workspace config form handlers
   */
  private setupWorkspaceForm(): void {
    if (!this.element) return;

    const form = this.element.querySelector("#workspace-config-form") as HTMLFormElement;
    if (!form) return;

    const cancelButton = form.querySelector(".btn-cancel");

    // Add debounced input listener to track dirty state
    form.addEventListener('input', () => {
      if (this.workspaceDebounceTimer) {
        window.clearTimeout(this.workspaceDebounceTimer);
      }
      this.workspaceDebounceTimer = window.setTimeout(() => {
        this.setDirty('workspace', true);
      }, 100);
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await this.saveWorkspaceConfig();
    });

    cancelButton?.addEventListener("click", () => {
      this.populateWorkspaceForm();
      this.setDirty('workspace', false);
      this.showMessage("Changes discarded", "info");
    });
  }

  private async saveWorkspaceConfig(): Promise<void> {
    if (!this.element) return;

    const form = this.element.querySelector("#workspace-config-form") as HTMLFormElement;
    const formData = new FormData(form);

    // Build values from form data
    const values: Record<string, unknown> = {};
    formData.forEach((value, key) => {
      values[key] = key === "server_port" ? parseInt(value as string, 10) : value;
    });

    // Validate
    const validation = this.validateWorkspaceConfig(values);
    if (!validation.valid) {
      this.showValidationErrors(form, validation.errors);
      this.showMessage("Please fix validation errors", "error");
      return;
    }

    // Get only changed values
    const changes = this.getChangedValues(formData, this.originalWorkspaceConfig);
    
    // Nothing to save if no changes
    if (Object.keys(changes).length === 0) {
      this.showMessage("No changes to save", "info");
      return;
    }

    // Set loading state
    this.isSavingWorkspace = true;
    this.updateSaveButtonState('workspace');

    try {
      const result = await updateConfig(changes);
      // Check if destroyed while waiting for API response
      if (this.isDestroyed) return;
      if (result.ok) {
        this.showMessage("Settings saved successfully", "success");
        this.workspaceConfig = { ...this.workspaceConfig, ...changes };
        this.originalWorkspaceConfig = { ...this.originalWorkspaceConfig, ...changes };
        this.displayConfig();
        this.setDirty('workspace', false);
      } else {
        this.showMessage("Failed to save settings. Please try again.", "error");
      }
    } catch (error) {
      const errorMessage = formatApiError(error);
      this.showMessage(errorMessage, "error", () => this.saveWorkspaceConfig());
    } finally {
      this.isSavingWorkspace = false;
      this.updateSaveButtonState('workspace');
    }
  }

  /**
   * Update save button state (loading/disabled)
   */
  private updateSaveButtonState(type: 'workspace' | 'repo'): void {
    if (!this.element) return;

    const formId = type === 'workspace' ? '#workspace-config-form' : '#repo-config-form';
    const saveButton = this.element.querySelector(`${formId} .btn-save`) as HTMLButtonElement;
    if (!saveButton) return;

    const isSaving = type === 'workspace' ? this.isSavingWorkspace : this.isSavingRepo;

    saveButton.disabled = isSaving;
    saveButton.textContent = isSaving ? 'Saving...' : (type === 'workspace' ? 'Save' : 'Save Repo Config');
  }

  /**
   * Setup repo selector dropdown
   */
  private setupRepoSelector(): void {
    if (!this.element) return;

    const select = this.element.querySelector("#repo-select") as HTMLSelectElement;
    if (!select) return;

    // Clear and repopulate options
    select.innerHTML = '<option value="">Workspace (Global Settings)</option>';
    const { repos } = getState();
    const repoNames = new Set<string>();
    repos.forEach(repo => {
      repoNames.add(repo.name);
      const option = document.createElement("option");
      option.value = repo.name;
      option.textContent = repo.name;
      select.appendChild(option);
    });

    // Check if currently selected repo still exists, reset if not
    if (this.selectedRepo && !repoNames.has(this.selectedRepo)) {
      this.selectedRepo = null;
      this.setRepoConfigVisible(false);
    } else if (this.selectedRepo) {
      // Preserve selection
      select.value = this.selectedRepo;
    }

    // Single listener (cloning not needed since we control listener attachment)
    select.addEventListener("change", async () => {
      this.selectedRepo = select.value || null;
      if (this.selectedRepo) {
        await this.loadRepoConfig(this.selectedRepo);
      } else {
        this.setRepoConfigVisible(false);
      }
    });
  }

  private async loadRepoConfig(repoName: string): Promise<void> {
    if (!this.element) return;

    try {
      const config = await getRepoConfig(repoName);
      // Check if destroyed while waiting for API response
      if (this.isDestroyed) return;
      this.repoConfigs[repoName] = config.merged || {};
      this.setRepoConfigVisible(true);
      this.populateRepoForm();
    } catch (error) {
      const errorMessage = formatApiError(error);
      this.showMessage(`Failed to load repo config: ${errorMessage}`, "error");
    }
  }

  /**
   * Show/hide repo config container
   */
  private setRepoConfigVisible(visible: boolean): void {
    if (!this.element) return;

    const container = this.element.querySelector("#repo-config-container") as HTMLElement;
    if (container) {
      container.style.display = visible ? "block" : "none";
    }
  }

  /**
   * Populate repo config form with current values
   */
  private populateRepoForm(): void {
    if (!this.element || !this.selectedRepo) return;

    const form = this.element.querySelector("#repo-config-form") as HTMLFormElement;
    if (!form) return;

    const config = this.repoConfigs[this.selectedRepo] || {};

    // Save original config for change detection
    this.originalRepoConfig = { ...config };

    // Clear validation errors
    form.querySelectorAll('.field-error').forEach((el) => el.remove());
    form.querySelectorAll('.input-error').forEach((el) => el.classList.remove('input-error'));

    // Populate repo fields using constant
    SettingsPage.REPO_FIELDS.forEach(field => {
      const input = form.querySelector(`[name="repo_${field}"]`) as HTMLInputElement;
      if (input && config[field] !== undefined) {
        input.value = String(config[field]);
      }
    });
  }

  /**
   * Setup repo config form handlers
   */
  private setupRepoForm(): void {
    if (!this.element) return;

    const form = this.element.querySelector("#repo-config-form") as HTMLFormElement;
    const cancelButton = form.querySelector(".btn-cancel");

    // Add debounced input listener to track dirty state
    form.addEventListener('input', () => {
      if (this.repoDebounceTimer) {
        window.clearTimeout(this.repoDebounceTimer);
      }
      this.repoDebounceTimer = window.setTimeout(() => {
        this.setDirty('repo', true);
      }, 100);
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await this.saveRepoConfig();
    });

    cancelButton?.addEventListener("click", () => {
      if (this.selectedRepo) {
        this.populateRepoForm();
        this.setDirty('repo', false);
        this.showMessage("Repo changes discarded", "info");
      }
    });
  }

  private async saveRepoConfig(): Promise<void> {
    if (!this.element || !this.selectedRepo) return;

    const form = this.element.querySelector("#repo-config-form") as HTMLFormElement;
    const formData = new FormData(form);
    const values: Record<string, unknown> = {};

    formData.forEach((value, key) => {
      values[key.replace("repo_", "")] = value;
    });

    // Validate
    const validation = this.validateRepoConfig(values);
    if (!validation.valid) {
      this.showValidationErrors(form, validation.errors);
      this.showMessage("Please fix validation errors", "error");
      return;
    }

    // Get only changed values
    const changes = this.getChangedValues(formData, this.originalRepoConfig);
    
    // Nothing to save if no changes
    if (Object.keys(changes).length === 0) {
      this.showMessage("No changes to save", "info");
      return;
    }

    // Set loading state
    this.isSavingRepo = true;
    this.updateSaveButtonState('repo');

    try {
      const result = await updateRepoConfig(this.selectedRepo, changes, false);
      // Check if destroyed while waiting for API response
      if (this.isDestroyed) return;
      if (result.ok) {
        this.showMessage(`Repo config saved for ${this.selectedRepo}`, "success");
        const loadedEl = this.element.querySelector(".repo-config-loaded") as HTMLElement;
        if (loadedEl) {
          loadedEl.textContent = "Configuration saved!";
          loadedEl.style.display = "block";
          setTimeout(() => {
            if (loadedEl) loadedEl.style.display = "none";
          }, 3000);
        }
        // Update original config to reflect saved changes
        this.originalRepoConfig = { ...this.originalRepoConfig, ...changes };
        this.setDirty('repo', false);
      } else {
        this.showMessage(`Failed to save repo config. Please try again.`, "error");
      }
    } catch (error) {
      const errorMessage = formatApiError(error);
      this.showMessage(errorMessage, "error", () => this.saveRepoConfig());
    } finally {
      this.isSavingRepo = false;
      this.updateSaveButtonState('repo');
    }
  }

  private showMessage(text: string, type: "success" | "error" | "info", onRetry?: () => void): void {
    if (!this.element) return;

    const messageEl = this.element.querySelector("#settings-message") as HTMLElement;
    if (messageEl) {
      // Clear any existing auto-hide timer
      if (this.messageAutoHideTimer) {
        window.clearTimeout(this.messageAutoHideTimer);
        this.messageAutoHideTimer = null;
      }

      messageEl.textContent = '';
      messageEl.className = `message ${type}`;
      messageEl.style.display = "block";

      // Create text span
      const textSpan = document.createElement('span');
      textSpan.className = 'message-text';
      textSpan.textContent = text;
      messageEl.appendChild(textSpan);

      // Add close button
      const closeButton = document.createElement('button');
      closeButton.className = 'message-close';
      closeButton.textContent = '×';
      closeButton.setAttribute('aria-label', 'Close message');
      closeButton.addEventListener('click', () => {
        messageEl.style.display = 'none';
        if (this.messageAutoHideTimer) {
          window.clearTimeout(this.messageAutoHideTimer);
          this.messageAutoHideTimer = null;
        }
      });
      messageEl.appendChild(closeButton);

      // Add retry button for errors
      if (type === 'error' && onRetry) {
        const retryButton = document.createElement('button');
        retryButton.className = 'retry-btn';
        retryButton.textContent = 'Retry';
        retryButton.addEventListener('click', () => {
          onRetry();
        });
        messageEl.appendChild(retryButton);
      }

      // Auto-hide after 5 seconds (only for success/info without retry)
      if (type !== 'error') {
        this.messageAutoHideTimer = window.setTimeout(() => {
          if (messageEl.style.display !== 'none') {
            messageEl.style.display = 'none';
          }
          this.messageAutoHideTimer = null;
        }, 5000);
      }
    }
  }
}
