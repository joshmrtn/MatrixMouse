/**
 * Unit Tests for SettingsPage Component
 *
 * Tests workspace and repo configuration management.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { SettingsPage } from '../../../src/pages/SettingsPage';

// Mock API functions
const mockGetConfig = vi.fn();
const mockUpdateConfig = vi.fn();
const mockGetRepoConfig = vi.fn();
const mockUpdateRepoConfig = vi.fn();

vi.mock('../../../src/api', () => ({
  getConfig: () => mockGetConfig(),
  updateConfig: (values: Record<string, unknown>) => mockUpdateConfig(values),
  getRepoConfig: (repoName: string) => mockGetRepoConfig(repoName),
  updateRepoConfig: (repoName: string, values: Record<string, unknown>, commit: boolean) =>
    mockUpdateRepoConfig(repoName, values, commit),
}));

// Mock state
const mockRepos = [
  { name: 'main-repo', remote: 'https://github.com/test/main.git', local_path: '/test/main', added: '2024-01-01' },
  { name: 'test-repo', remote: 'https://github.com/test/test.git', local_path: '/test/test', added: '2024-01-01' },
];

vi.mock('../../../src/state', () => ({
  getState: () => ({ repos: mockRepos }),
  subscribe: vi.fn(),
}));

describe('SettingsPage', () => {
  let container: HTMLElement;
  let page: SettingsPage;

  const mockWorkspaceConfig = {
    coder_model: 'ollama:qwen3.5:4b',
    manager_model: 'ollama:qwen3.5:9b',
    critic_model: 'ollama:qwen3.5:9b',
    writer_model: 'ollama:qwen3.5:4b',
    summarizer_model: 'ollama:qwen3.5:2b',
    agent_git_name: 'MatrixMouse Bot',
    agent_git_email: 'matrixmouse@example.com',
    server_port: 8080,
    log_level: 'INFO',
  };

  const mockRepoConfig = {
    local: { coder_model: 'ollama:custom:1b' },
    committed: {},
    merged: { coder_model: 'ollama:custom:1b' },
  };

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    page = new SettingsPage();

    vi.clearAllMocks();
  });

  afterEach(() => {
    page.destroy();
    document.body.removeChild(container);
  });

  describe('render', () => {
    it('renders settings page with all sections', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      expect(container.querySelector('#settings-page')).toBeTruthy();
      expect(container.querySelector('#repo-overrides')).toBeTruthy();
      expect(container.querySelector('#workspace-settings')).toBeTruthy();
    });

    it('renders repo selector with workspace option', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      expect(select).toBeTruthy();
      expect(select.options.length).toBe(3); // Workspace + 2 repos
      expect(select.options[0].text).toBe('Workspace (Global Settings)');
    });

    it('renders all model configuration fields', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const modelFields = [
        'coder_model',
        'manager_model',
        'critic_model',
        'writer_model',
        'summarizer_model',
      ];

      modelFields.forEach((field) => {
        const input = container.querySelector(`[name="${field}"]`);
        expect(input).toBeTruthy();
      });
    });

    it('renders agent identity fields', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      expect(container.querySelector('[name="agent_git_name"]')).toBeTruthy();
      expect(container.querySelector('[name="agent_git_email"]')).toBeTruthy();
    });

    it('renders server configuration fields', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      expect(container.querySelector('[name="server_port"]')).toBeTruthy();
      expect(container.querySelector('[name="log_level"]')).toBeTruthy();
    });

    it('renders form action buttons', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const workspaceForm = container.querySelector('#workspace-config-form');
      expect(workspaceForm?.querySelector('.btn-save')).toBeTruthy();
      expect(workspaceForm?.querySelector('.btn-cancel')).toBeTruthy();
    });

    it('renders repo config form with all model fields', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      // Select a repo to show repo config
      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      select.value = 'main-repo';
      select.dispatchEvent(new Event('change'));

      // Wait for async load
      await new Promise((resolve) => setTimeout(resolve, 10));

      const repoForm = container.querySelector('#repo-config-form');
      expect(repoForm).toBeTruthy();
      expect(repoForm?.querySelector('[name="repo_coder_model"]')).toBeTruthy();
      expect(repoForm?.querySelector('[name="repo_manager_model"]')).toBeTruthy();
      expect(repoForm?.querySelector('[name="repo_critic_model"]')).toBeTruthy();
      expect(repoForm?.querySelector('[name="repo_writer_model"]')).toBeTruthy();
      expect(repoForm?.querySelector('[name="repo_summarizer_model"]')).toBeTruthy();
    });
  });

  describe('config loading', () => {
    it('populates workspace form with current config values', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const coderModelInput = container.querySelector('[name="coder_model"]') as HTMLInputElement;
      expect(coderModelInput.value).toBe('ollama:qwen3.5:4b');

      const portInput = container.querySelector('[name="server_port"]') as HTMLInputElement;
      expect(portInput.value).toBe('8080');
    });

    it('handles config load error gracefully', async () => {
      mockGetConfig.mockRejectedValue(new Error('Failed to load'));

      await page.render(container);

      const messageEl = container.querySelector('#settings-message');
      expect(messageEl).toBeTruthy();
      expect(messageEl?.className).toContain('error');
    });
  });

  describe('workspace config validation', () => {
    it('validates server_port is in valid range (1-65535)', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['server_port'] });

      await page.render(container);

      const portInput = container.querySelector('[name="server_port"]') as HTMLInputElement;
      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;

      // Test invalid port (too high)
      portInput.value = '70000';
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      // Should not call API with invalid value
      expect(mockUpdateConfig).not.toHaveBeenCalled();
    });

    it('validates server_port is not negative', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['server_port'] });

      await page.render(container);

      const portInput = container.querySelector('[name="server_port"]') as HTMLInputElement;
      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;

      portInput.value = '-1';
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      expect(mockUpdateConfig).not.toHaveBeenCalled();
    });

    it('validates agent_git_email format', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['agent_git_email'] });

      await page.render(container);

      const emailInput = container.querySelector('[name="agent_git_email"]') as HTMLInputElement;
      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;

      emailInput.value = 'not-an-email';
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      // Should not call API with invalid email
      expect(mockUpdateConfig).not.toHaveBeenCalled();
    });

    it('allows valid email addresses', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['agent_git_email'] });

      await page.render(container);

      const emailInput = container.querySelector('[name="agent_git_email"]') as HTMLInputElement;
      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;

      emailInput.value = 'valid+email@example.com';
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      // Should call API with valid email
      expect(mockUpdateConfig).toHaveBeenCalled();
    });

    it('validates model fields are not empty', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['coder_model'] });

      await page.render(container);

      const modelInput = container.querySelector('[name="coder_model"]') as HTMLInputElement;
      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;

      modelInput.value = '';
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      // Should not call API with empty model
      expect(mockUpdateConfig).not.toHaveBeenCalled();
    });

    it('allows model names with host:backend:model format', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['coder_model'] });

      await page.render(container);

      const modelInput = container.querySelector('[name="coder_model"]') as HTMLInputElement;
      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;

      const validModels = [
        '192.168.1.19:ollama:qwen3.5:9b',
        'anthropic:claude-sonnet-4-5',
        'ollama:qwen3.5:4b',
        'openai:gpt-4',
      ];

      for (const model of validModels) {
        modelInput.value = model;
        mockUpdateConfig.mockClear();
        (page as any).originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'different' };
        form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));
        expect(mockUpdateConfig).toHaveBeenCalled();
      }
    });
  });

  describe('workspace config save', () => {
    it('saves valid workspace config changes', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['coder_model'] });

      await page.render(container);

      const coderModelInput = container.querySelector('[name="coder_model"]') as HTMLInputElement;
      coderModelInput.value = 'ollama:new-model:7b';

      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      expect(mockUpdateConfig).toHaveBeenCalledWith({ coder_model: 'ollama:new-model:7b' });
    });

    it('shows success message after save', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['coder_model'] });

      await page.render(container);

      const pageAny = page as any;
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'original' };

      const coderModelInput = container.querySelector('[name="coder_model"]') as HTMLInputElement;
      coderModelInput.value = 'ollama:changed:1b';

      await pageAny.saveConfig('workspace');

      const messageEl = container.querySelector('#settings-message');
      expect(messageEl?.className).toContain('success');
    });

    it('shows error message on save failure', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockRejectedValue(new Error('API error'));

      await page.render(container);

      const pageAny = page as any;
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'different' };

      await pageAny.saveConfig('workspace');

      const messageEl = container.querySelector('#settings-message');
      expect(messageEl?.className).toContain('error');
    });

    it('updates form values after successful save', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['coder_model'] });

      await page.render(container);

      const coderModelInput = container.querySelector('[name="coder_model"]') as HTMLInputElement;
      coderModelInput.value = 'ollama:updated:7b';

      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      expect(coderModelInput.value).toBe('ollama:updated:7b');
    });

    it('shows info message when no changes to save', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      const messageEl = container.querySelector('#settings-message');
      expect(messageEl?.className).toContain('info');
      expect(messageEl?.textContent).toContain('No changes to save');
    });
  });

  describe('cancel button', () => {
    it('resets form to original values', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const coderModelInput = container.querySelector('[name="coder_model"]') as HTMLInputElement;
      const cancelButton = container.querySelector('#workspace-config-form .btn-cancel') as HTMLButtonElement;

      coderModelInput.value = 'ollama:changed:1b';
      cancelButton.click();

      expect(coderModelInput.value).toBe('ollama:qwen3.5:4b');
    });

    it('shows info message when cancelled', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const cancelButton = container.querySelector('#workspace-config-form .btn-cancel') as HTMLButtonElement;
      cancelButton.click();

      const messageEl = container.querySelector('#settings-message');
      expect(messageEl?.className).toContain('info');
    });
  });

  describe('repo selector', () => {
    it('populates repo selector with available repos', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      const options = Array.from(select.options);

      expect(options.length).toBe(3);
      expect(options.map((o) => o.value)).toContain('main-repo');
      expect(options.map((o) => o.value)).toContain('test-repo');
    });

    it('loads repo config when repo is selected', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockGetRepoConfig.mockResolvedValue(mockRepoConfig);

      await page.render(container);

      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      select.value = 'main-repo';
      select.dispatchEvent(new Event('change'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(mockGetRepoConfig).toHaveBeenCalledWith('main-repo');
    });

    it('hides repo config when workspace is selected', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      select.value = '';
      select.dispatchEvent(new Event('change'));

      const repoConfigContainer = container.querySelector('#repo-config-container');
      expect(repoConfigContainer?.getAttribute('style')).toContain('display: none');
    });
  });

  describe('repo config', () => {
    beforeEach(() => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockGetRepoConfig.mockResolvedValue(mockRepoConfig);
    });

    it('populates repo form with repo-specific values', async () => {
      await page.render(container);

      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      select.value = 'main-repo';
      select.dispatchEvent(new Event('change'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      const repoCoderModel = container.querySelector('[name="repo_coder_model"]') as HTMLInputElement;
      expect(repoCoderModel.value).toBe('ollama:custom:1b');
    });

    it('saves repo-specific config', async () => {
      mockUpdateRepoConfig.mockResolvedValue({ ok: true, updated: ['coder_model'] });

      await page.render(container);

      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      select.value = 'main-repo';
      select.dispatchEvent(new Event('change'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      const pageAny = page as any;
      pageAny.selectedRepo = 'main-repo';
      pageAny.originalRepoConfig = {
        coder_model: 'original',
        manager_model: 'original',
        critic_model: 'original',
        writer_model: 'original',
        summarizer_model: 'original',
      };

      const repoCoderModel = container.querySelector('[name="repo_coder_model"]') as HTMLInputElement;
      const repoManagerModel = container.querySelector('[name="repo_manager_model"]') as HTMLInputElement;
      const repoCriticModel = container.querySelector('[name="repo_critic_model"]') as HTMLInputElement;
      const repoWriterModel = container.querySelector('[name="repo_writer_model"]') as HTMLInputElement;
      const repoSummarizerModel = container.querySelector('[name="repo_summarizer_model"]') as HTMLInputElement;

      repoCoderModel.value = 'ollama:repo-specific:2b';
      repoManagerModel.value = 'ollama:manager:1b';
      repoCriticModel.value = 'ollama:critic:1b';
      repoWriterModel.value = 'ollama:writer:1b';
      repoSummarizerModel.value = 'ollama:summarizer:1b';

      await pageAny.saveConfig('repo');

      expect(mockUpdateRepoConfig).toHaveBeenCalledWith('main-repo', {
        coder_model: 'ollama:repo-specific:2b',
        manager_model: 'ollama:manager:1b',
        critic_model: 'ollama:critic:1b',
        writer_model: 'ollama:writer:1b',
        summarizer_model: 'ollama:summarizer:1b',
      }, false);
    });

    it('shows success message after repo config save', async () => {
      mockUpdateRepoConfig.mockResolvedValue({ ok: true, updated: ['coder_model'] });

      await page.render(container);

      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      select.value = 'main-repo';
      select.dispatchEvent(new Event('change'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      const pageAny = page as any;
      pageAny.selectedRepo = 'main-repo';
      pageAny.originalRepoConfig = {
        coder_model: 'original',
        manager_model: 'original',
        critic_model: 'original',
        writer_model: 'original',
        summarizer_model: 'original',
      };

      const repoCoderModel = container.querySelector('[name="repo_coder_model"]') as HTMLInputElement;
      const repoManagerModel = container.querySelector('[name="repo_manager_model"]') as HTMLInputElement;
      const repoCriticModel = container.querySelector('[name="repo_critic_model"]') as HTMLInputElement;
      const repoWriterModel = container.querySelector('[name="repo_writer_model"]') as HTMLInputElement;
      const repoSummarizerModel = container.querySelector('[name="repo_summarizer_model"]') as HTMLInputElement;

      repoCoderModel.value = 'ollama:changed:1b';
      repoManagerModel.value = 'ollama:manager:1b';
      repoCriticModel.value = 'ollama:critic:1b';
      repoWriterModel.value = 'ollama:writer:1b';
      repoSummarizerModel.value = 'ollama:summarizer:1b';

      await pageAny.saveConfig('repo');

      const messageEl = container.querySelector('#settings-message');
      expect(messageEl?.className).toContain('success');
    });

    it('allows empty repo model fields (optional overrides)', async () => {
      mockUpdateRepoConfig.mockResolvedValue({ ok: true, updated: ['coder_model'] });

      await page.render(container);

      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      select.value = 'main-repo';
      select.dispatchEvent(new Event('change'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      // Set at least one non-empty field to avoid "no changes" short-circuit
      const pageAny = page as any;
      pageAny.selectedRepo = 'main-repo';
      pageAny.originalRepoConfig = { coder_model: 'original' };

      const repoCoderModel = container.querySelector('[name="repo_coder_model"]') as HTMLInputElement;
      repoCoderModel.value = 'ollama:changed:1b';

      // Leave other fields empty — this should be allowed
      const form = container.querySelector('#repo-config-form') as HTMLFormElement;
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      // The API call should be made with the non-empty changed value
      expect(mockUpdateRepoConfig).toHaveBeenCalledWith('main-repo', {
        coder_model: 'ollama:changed:1b',
      }, false);
    });
  });

  describe('message display', () => {
    it('displays different styles for different message types', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const pageAny = page as any;

      pageAny.showMessage('Success!', 'success');
      let messageEl = container.querySelector('#settings-message') as HTMLElement;
      expect(messageEl.className).toContain('success');

      pageAny.showMessage('Error!', 'error');
      messageEl = container.querySelector('#settings-message') as HTMLElement;
      expect(messageEl.className).toContain('error');

      pageAny.showMessage('Info!', 'info');
      messageEl = container.querySelector('#settings-message') as HTMLElement;
      expect(messageEl.className).toContain('info');
    });

    it('hides message when hideMessage is called', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const pageAny = page as any;
      pageAny.showMessage('Test message', 'success');

      let messageEl = container.querySelector('#settings-message') as HTMLElement;
      expect(messageEl.style.display).toBe('block');

      pageAny.hideMessage();
      messageEl = container.querySelector('#settings-message') as HTMLElement;
      expect(messageEl.style.display).toBe('none');
    });
  });

  describe('loading states', () => {
    it('disables save button during save operation', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve({ ok: true, updated: ['coder_model'] }), 100)));

      await page.render(container);

      const pageAny = page as any;
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'different' };

      const savePromise = pageAny.saveConfig('workspace');

      const saveButton = container.querySelector('#workspace-config-form .btn-save') as HTMLButtonElement;
      expect(saveButton.disabled).toBe(true);

      await savePromise;
    });

    it('re-enables save button after save completes', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['coder_model'] });

      await page.render(container);

      const pageAny = page as any;
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'different' };

      await pageAny.saveConfig('workspace');

      const saveButton = container.querySelector('#workspace-config-form .btn-save') as HTMLButtonElement;
      expect(saveButton.disabled).toBe(false);
    });

    it('shows loading text on save button during operation', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve({ ok: true, updated: ['coder_model'] }), 10)));

      await page.render(container);

      const pageAny = page as any;
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'different' };

      const savePromise = pageAny.saveConfig('workspace');

      const saveButton = container.querySelector('#workspace-config-form .btn-save') as HTMLButtonElement;
      expect(saveButton.textContent).toContain('Saving');

      await savePromise;
    });

    it('disables repo save button during save operation', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateRepoConfig.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve({ ok: true, updated: ['coder_model'] }), 100)));

      await page.render(container);

      const select = container.querySelector('#repo-select') as HTMLSelectElement;
      select.value = 'main-repo';
      select.dispatchEvent(new Event('change'));

      await new Promise((resolve) => setTimeout(resolve, 10));

      const pageAny = page as any;
      pageAny.selectedRepo = 'main-repo';
      pageAny.originalRepoConfig = {
        coder_model: 'original',
        manager_model: 'original',
        critic_model: 'original',
        writer_model: 'original',
        summarizer_model: 'original',
      };

      const repoCoderModel = container.querySelector('[name="repo_coder_model"]') as HTMLInputElement;
      const repoManagerModel = container.querySelector('[name="repo_manager_model"]') as HTMLInputElement;
      const repoCriticModel = container.querySelector('[name="repo_critic_model"]') as HTMLInputElement;
      const repoWriterModel = container.querySelector('[name="repo_writer_model"]') as HTMLInputElement;
      const repoSummarizerModel = container.querySelector('[name="repo_summarizer_model"]') as HTMLInputElement;

      repoCoderModel.value = 'ollama:changed:1b';
      repoManagerModel.value = 'ollama:manager:1b';
      repoCriticModel.value = 'ollama:critic:1b';
      repoWriterModel.value = 'ollama:writer:1b';
      repoSummarizerModel.value = 'ollama:summarizer:1b';

      const savePromise = pageAny.saveConfig('repo');

      await new Promise((resolve) => setTimeout(resolve, 1));

      const saveButton = container.querySelector('#repo-config-form .btn-save') as HTMLButtonElement;
      expect(saveButton.disabled).toBe(true);

      await savePromise;
    });
  });

  describe('error handling', () => {
    it('displays detailed error message from API', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockRejectedValue(new Error('API Error: Invalid model format'));

      await page.render(container);

      const pageAny = page as any;
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'different' };

      await pageAny.saveConfig('workspace');

      const messageEl = container.querySelector('#settings-message') as HTMLElement;
      expect(messageEl.textContent).toContain('Invalid model format');
    });

    it('handles network errors gracefully', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockRejectedValue(new TypeError('Failed to fetch'));

      await page.render(container);

      const pageAny = page as any;
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'different' };

      await pageAny.saveConfig('workspace');

      const messageEl = container.querySelector('#settings-message') as HTMLElement;
      expect(messageEl.className).toContain('error');
      expect(messageEl.textContent.toLowerCase()).toContain('network');
    });
  });

  describe('validation error display', () => {
    it('displays all validation errors when multiple exist', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;

      const pageAny = page as any;
      const errors = {
        server_port: 'Invalid port',
        agent_git_email: 'Invalid email',
        coder_model: 'Empty model',
      };
      pageAny.showValidationErrors(form, errors);

      const errorElements = form.querySelectorAll('.field-error');
      expect(errorElements.length).toBe(3);

      const errorTexts = Array.from(errorElements).map(el => el.textContent);
      expect(errorTexts).toContain('Invalid port');
      expect(errorTexts).toContain('Invalid email');
      expect(errorTexts).toContain('Empty model');
    });
  });

  describe('refresh', () => {
    it('has manual refresh button', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const refreshBtn = container.querySelector('.refresh-config-btn');
      expect(refreshBtn).toBeTruthy();
      expect(refreshBtn?.getAttribute('aria-label')).toContain('Refresh');
    });

    it('reloads config when refresh button is clicked', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      const updatedConfig = { ...mockWorkspaceConfig, coder_model: 'ollama:updated:7b' };
      mockGetConfig.mockResolvedValueOnce(mockWorkspaceConfig);
      mockGetConfig.mockResolvedValueOnce(updatedConfig);

      await page.render(container);

      const refreshBtn = container.querySelector('.refresh-config-btn') as HTMLButtonElement;
      refreshBtn.click();

      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(mockGetConfig).toHaveBeenCalledTimes(2);
    });

    it('shows loading state during refresh', async () => {
      mockGetConfig.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve(mockWorkspaceConfig), 100)));

      await page.render(container);

      const refreshBtn = container.querySelector('.refresh-config-btn') as HTMLButtonElement;
      refreshBtn.click();

      expect(refreshBtn.disabled).toBe(true);
      expect(refreshBtn.textContent).toContain('Refreshing');
    });

    it('prevents concurrent refresh operations', async () => {
      let callCount = 0;
      mockGetConfig.mockImplementation(() => {
        callCount++;
        return new Promise(resolve =>
          setTimeout(() => resolve(mockWorkspaceConfig), 200)
        );
      });

      await page.render(container);
      callCount = 0;

      const pageAny = page as any;
      const firstRefresh = pageAny.refreshConfig();

      await new Promise(resolve => setTimeout(resolve, 50));
      await pageAny.refreshConfig();

      await firstRefresh;
      expect(callCount).toBe(1);
    });

    it('shows info message when refreshing during save', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve({ ok: true }), 100)));

      await page.render(container);

      const pageAny = page as any;
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'different' };
      pageAny.isSavingWorkspace = true;

      await pageAny.refreshConfig();

      const messageEl = container.querySelector('#settings-message') as HTMLElement;
      expect(messageEl.textContent).toContain('Cannot refresh while saving');

      pageAny.isSavingWorkspace = false;
    });
  });

  describe('accessibility', () => {
    it('has ARIA labels on all model input fields', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const modelFields = [
        { name: 'coder_model', label: 'Coder Model' },
        { name: 'manager_model', label: 'Manager Model' },
        { name: 'critic_model', label: 'Critic Model' },
        { name: 'writer_model', label: 'Writer Model' },
        { name: 'summarizer_model', label: 'Summarizer Model' },
      ];

      modelFields.forEach(({ name, label }) => {
        const input = container.querySelector(`[name="${name}"]`);
        expect(input?.getAttribute('aria-label')).toBe(label);
      });
    });

    it('has ARIA labels on identity fields', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const gitNameInput = container.querySelector('[name="agent_git_name"]');
      const gitEmailInput = container.querySelector('[name="agent_git_email"]');

      expect(gitNameInput?.getAttribute('aria-label')).toBe('Git Name');
      expect(gitEmailInput?.getAttribute('aria-label')).toBe('Git Email');
    });

    it('has ARIA labels on server config fields', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const portInput = container.querySelector('[name="server_port"]');
      const logLevelSelect = container.querySelector('[name="log_level"]');

      expect(portInput?.getAttribute('aria-label')).toBe('Server Port');
      expect(logLevelSelect?.getAttribute('aria-label')).toBe('Log Level');
    });

    it('has ARIA live region for messages', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const messageEl = container.querySelector('#settings-message');
      expect(messageEl?.getAttribute('role')).toBe('alert');
      expect(messageEl?.getAttribute('aria-live')).toBe('assertive');
    });

    it('has ARIA labels on save buttons', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const workspaceSaveBtn = container.querySelector('#workspace-config-form .btn-save');
      const repoSaveBtn = container.querySelector('#repo-config-form .btn-save');

      expect(workspaceSaveBtn?.getAttribute('aria-label')).toContain('Save workspace');
      expect(repoSaveBtn?.getAttribute('aria-label')).toContain('Save repo');
    });
  });

  describe('destroy() cleanup', () => {
    it('unsubscribes from state', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      const mockUnsubscribe = vi.fn();

      const { subscribe } = await import('../../../src/state');
      vi.mocked(subscribe).mockImplementation((callback) => {
        callback({ repos: mockRepos, scope: 'workspace', tasks: [], expandedTasks: new Set(), blockedReport: null, status: null, pendingQuestion: null, wsConnected: false, currentPage: 'settings', routeParams: {}, sidebarOpen: false, loading: false, error: null });
        return mockUnsubscribe;
      });

      const newPage = new SettingsPage();
      await newPage.render(container);

      newPage.destroy();

      expect(mockUnsubscribe).toHaveBeenCalled();
    });

    it('resets all state flags', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      page.destroy();

      expect((page as any).isDestroyed).toBe(true);
      expect((page as any).selectedRepo).toBeNull();
      expect((page as any).element).toBeNull();
    });

    it('isDestroyed prevents async state updates', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve({ ok: true }), 50)));

      await page.render(container);

      const pageAny = page as any;
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, coder_model: 'different' };

      // Start save
      const savePromise = pageAny.saveConfig('workspace');

      // Destroy while save is in progress
      page.destroy();

      await savePromise;

      // Should not crash or update after destroy
      expect(pageAny.isDestroyed).toBe(true);
    });
  });

  describe('reposChanged() helper', () => {
    it('returns true when repo count changes', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const pageAny = page as any;
      pageAny.lastRepoList = ['repo1', 'repo2'];

      expect(pageAny.reposChanged(['repo1', 'repo2', 'repo3'])).toBe(true);
    });

    it('returns true when repo names change', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const pageAny = page as any;
      pageAny.lastRepoList = ['repo1', 'repo2'];

      expect(pageAny.reposChanged(['repo1', 'repo3'])).toBe(true);
    });

    it('returns false when repos are identical', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const pageAny = page as any;
      pageAny.lastRepoList = ['repo1', 'repo2'];

      expect(pageAny.reposChanged(['repo1', 'repo2'])).toBe(false);
    });

    it('handles empty repo list', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const pageAny = page as any;
      pageAny.lastRepoList = ['repo1'];

      expect(pageAny.reposChanged([])).toBe(true);
    });
  });

  describe('setFormDisabled', () => {
    it('disables all form inputs when called with true', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const pageAny = page as any;
      pageAny.setFormDisabled(true);

      const inputs = container.querySelectorAll('#workspace-config-form input, #workspace-config-form select, #workspace-config-form button[type="submit"]');
      inputs.forEach(input => {
        expect((input as HTMLInputElement).disabled).toBe(true);
      });
    });

    it('enables all form inputs when called with false', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const pageAny = page as any;
      pageAny.setFormDisabled(true);
      pageAny.setFormDisabled(false);

      const inputs = container.querySelectorAll('#workspace-config-form input, #workspace-config-form select, #workspace-config-form button[type="submit"]');
      inputs.forEach(input => {
        expect((input as HTMLInputElement).disabled).toBe(false);
      });
    });

    it('also disables refresh button', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const pageAny = page as any;
      pageAny.setFormDisabled(true);

      const refreshBtn = container.querySelector('.refresh-config-btn') as HTMLButtonElement;
      expect(refreshBtn.disabled).toBe(true);
    });
  });

  describe('edge cases', () => {
    it('parses number values correctly in changed values detection', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);
      mockUpdateConfig.mockResolvedValue({ ok: true, updated: ['server_port'] });

      await page.render(container);

      const pageAny = page as any;
      // Set original with different port so change is detected
      pageAny.originalWorkspaceConfig = { ...mockWorkspaceConfig, server_port: 9090 };

      const portInput = container.querySelector('[name="server_port"]') as HTMLInputElement;
      portInput.value = '8080';

      const form = container.querySelector('#workspace-config-form') as HTMLFormElement;
      form.dispatchEvent(new SubmitEvent('submit', { cancelable: true }));

      // server_port should be parsed as a number, not a string
      expect(mockUpdateConfig).toHaveBeenCalledWith({ server_port: 8080 });
    });

    it('handles repo cancel button when no repo selected', async () => {
      mockGetConfig.mockResolvedValue(mockWorkspaceConfig);

      await page.render(container);

      const cancelButton = container.querySelector('#repo-config-form .btn-cancel') as HTMLButtonElement;
      cancelButton.click();

      // Should not crash even though no repo is selected
      const messageEl = container.querySelector('#settings-message');
      expect(messageEl).toBeTruthy();
    });
  });
});
