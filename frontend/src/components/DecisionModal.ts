/**
 * DecisionBanner Component
 *
 * Non-blocking banner that appears in the task conversation view when
 * the agent requires human approval for a decision.
 *
 * Unlike a traditional modal, this banner does NOT block interaction
 * with the rest of the app — users can scroll conversation history,
 * read messages, and navigate freely while deciding.
 *
 * Listens for CustomEvents on window:
 * - decomposition_confirmation_required
 * - pr_approval_required
 * - turn_limit_reached
 * - planning_turn_limit_reached
 * - merge_conflict_resolution_turn_limit_reached
 * - critic_turn_limit_reached
 *
 * E2E Tests: frontend/tests/e2e/test_decision_modals.spec.ts
 */

import { escapeHtml } from '../utils';
import type {
  DecisionModalType,
  DecisionEventData,
  DecompositionEventData,
  PRApprovalEventData,
  TurnLimitEventData,
  PlanningTurnLimitEventData,
  MergeTurnLimitEventData,
  CriticTurnLimitEventData,
} from '../types/decision';

/** Primary actions get the primary button style */
const PRIMARY_ACTIONS = new Set(['allow', 'approve', 'extend', 'extend_critic']);

/**
 * Maps WebSocket event names to internal decision types
 */
const EVENT_NAME_TO_TYPE: Record<string, DecisionModalType> = {
  decomposition_confirmation_required: 'decomposition',
  pr_approval_required: 'pr_approval',
  turn_limit_reached: 'turn_limit',
  planning_turn_limit_reached: 'planning_turn_limit',
  merge_conflict_resolution_turn_limit_reached: 'merge_turn_limit',
  critic_turn_limit_reached: 'critic_turn_limit',
};

/**
 * Maps internal decision types to WebSocket event names (for API submission)
 */
const TYPE_TO_EVENT_NAME: Record<DecisionModalType, string> = {
  decomposition: 'decomposition_confirmation_required',
  pr_approval: 'pr_approval_required',
  turn_limit: 'turn_limit_reached',
  planning_turn_limit: 'planning_turn_limit_reached',
  merge_turn_limit: 'merge_conflict_resolution_turn_limit_reached',
  critic_turn_limit: 'critic_turn_limit_reached',
};

/**
 * Configuration for a single decision type.
 * bodyFields: each entry is either a raw HTML string, or a function that returns
 * HTML (the function result will be wrapped in <p>). If the function returns
 * null/undefined, that field is skipped.
 */
interface BannerConfig {
  /** Banner title text */
  title: string;
  /** Fields to render in the body. */
  bodyFields: Array<string | ((e: DecisionEventData) => string | null)>;
  /** If true, show denial textarea and require text for deny choice */
  showNote: boolean;
  /** Value that triggers denial flow (requires note if showNote is true) */
  denyChoiceValue?: string;
  /** Label for the denial textarea */
  noteLabel?: string;
}

/**
 * Data-driven configuration for all 6 decision banner types.
 * Each config specifies title, body fields, and whether a denial note is required.
 */
const BANNER_CONFIG: Record<DecisionModalType, BannerConfig> = {
  decomposition: {
    title: '\u26A0\uFE0F Decision Required: Task Decomposition',
    bodyFields: [
      (e) => {
        const d = e as DecompositionEventData;
        return 'Agent wants to split <strong>' + escapeHtml(d.task_title || d.task_id) + '</strong> into subtasks.';
      },
      (e) => {
        const d = e as DecompositionEventData;
        return 'Depth: <strong>' + (d.current_depth ?? 0) + '</strong> / <strong>' + (d.allowed_depth ?? 3) + '</strong> allowed';
      },
    ],
    showNote: true,
    denyChoiceValue: 'deny',
    noteLabel: 'Please explain why you are denying this decomposition:',
  },
  pr_approval: {
    title: '\u26A0\uFE0F Decision Required: Pull Request Approval',
    bodyFields: [
      (e) => {
        const d = e as PRApprovalEventData;
        return '<strong>' + escapeHtml(d.task_title || d.task_id) + '</strong>';
      },
      (e) => {
        const d = e as PRApprovalEventData;
        return 'Branch: <code>' + escapeHtml(d.branch) + '</code> &rarr; <code>' + escapeHtml(d.parent_branch) + '</code>';
      },
      (e) => {
        const d = e as PRApprovalEventData;
        return 'Repo: <code>' + escapeHtml(d.repo) + '</code>';
      },
    ],
    showNote: false,
  },
  turn_limit: {
    title: '\u26A0\uFE0F Decision Required: Turn Limit Reached',
    bodyFields: [
      (e) => {
        const d = e as TurnLimitEventData;
        return '<strong>' + escapeHtml(d.task_title || d.task_id) + '</strong>';
      },
      (e) => {
        const d = e as TurnLimitEventData;
        return 'Role: ' + escapeHtml(d.role || 'unknown');
      },
      (e) => {
        const d = e as TurnLimitEventData;
        return 'Turns: <strong>' + d.turns_taken + '</strong> / <strong>' + d.turn_limit + '</strong>';
      },
    ],
    showNote: false,
  },
  planning_turn_limit: {
    title: '\u26A0\uFE0F Decision Required: Planning Turn Limit',
    bodyFields: [
      (e) => {
        const d = e as PlanningTurnLimitEventData;
        return '<strong>' + escapeHtml(d.task_title || d.task_id) + '</strong>';
      },
      (e) => {
        const d = e as PlanningTurnLimitEventData;
        return 'Turns: <strong>' + d.turns_taken + '</strong>';
      },
    ],
    showNote: false,
  },
  merge_turn_limit: {
    title: '\u26A0\uFE0F Decision Required: Merge Turn Limit',
    bodyFields: [
      (e) => {
        const d = e as MergeTurnLimitEventData;
        return '<strong>' + escapeHtml(d.task_title || d.task_id) + '</strong>';
      },
      (e) => {
        const d = e as MergeTurnLimitEventData;
        return 'Turns: <strong>' + d.turns_taken + '</strong>';
      },
      (e) => {
        const d = e as MergeTurnLimitEventData;
        return 'Parent: <code>' + escapeHtml(d.parent_branch) + '</code>';
      },
      (e) => {
        const d = e as MergeTurnLimitEventData;
        if (d.resolved_so_far && d.resolved_so_far.length > 0) {
          return 'Resolved so far: ' + escapeHtml(d.resolved_so_far.map((r: { file: string }) => r.file).join(', '));
        }
        return null;
      },
    ],
    showNote: false,
  },
  critic_turn_limit: {
    title: '\u26A0\uFE0F Decision Required: Critic Turn Limit',
    bodyFields: [
      (e) => {
        const d = e as CriticTurnLimitEventData;
        return '<strong>' + escapeHtml(d.task_title || d.task_id) + '</strong>';
      },
      (e) => {
        const d = e as CriticTurnLimitEventData;
        return 'Turns: <strong>' + d.turns_taken + '</strong> / <strong>' + d.critic_max_turns + '</strong>';
      },
      (e) => {
        const d = e as CriticTurnLimitEventData;
        return 'Reviewed task: <code>' + escapeHtml(d.reviewed_task_id) + '</code>';
      },
    ],
    showNote: false,
  },
};

export class DecisionBanner {
  private element: HTMLElement | null = null;
  private titleEl: HTMLElement | null = null;
  private bodyEl: HTMLElement | null = null;
  private choicesEl: HTMLElement | null = null;
  private noteArea: HTMLTextAreaElement | null = null;
  private errorEl: HTMLElement | null = null;
  private collapseBtn: HTMLElement | null = null;

  /** Whether the banner is currently showing a pending decision — public for TaskPage access */
  isShowing = false;
  private isCollapsed = false;
  private currentType: DecisionModalType | null = null;
  private currentEvent: DecisionEventData | null = null;
  private pendingChoice: string | null = null;
  private requireTextForDeny = false;
  private isSubmitting = false;

  constructor() {
    // Event listeners set up in render()
  }

  /**
   * Create and return the banner element.
   * Renders into the provided container — NOT full-screen.
   */
  render(container: HTMLElement): HTMLElement {
    this.element = document.createElement('div');
    this.element.id = 'decision-banner';
    this.element.setAttribute('role', 'alert');
    this.element.setAttribute('aria-live', 'assertive');
    this.element.style.display = 'none';

    // Header row with title and collapse button
    const headerRow = document.createElement('div');
    headerRow.className = 'decision-banner-header';

    this.titleEl = document.createElement('h3');
    this.titleEl.id = 'decision-banner-title';

    this.collapseBtn = document.createElement('button');
    this.collapseBtn.className = 'decision-collapse-btn';
    this.collapseBtn.setAttribute('aria-label', 'Collapse decision banner');
    this.collapseBtn.innerHTML = '&#x25BC;';
    this.collapseBtn.addEventListener('click', () => this.toggleCollapse());

    headerRow.appendChild(this.titleEl);
    headerRow.appendChild(this.collapseBtn);

    // Body — hidden when collapsed
    const bodyWrapper = document.createElement('div');
    bodyWrapper.className = 'decision-banner-body';

    this.bodyEl = document.createElement('div');
    this.bodyEl.id = 'decision-banner-body';

    this.choicesEl = document.createElement('div');
    this.choicesEl.id = 'decision-banner-choices';

    bodyWrapper.appendChild(this.bodyEl);
    bodyWrapper.appendChild(this.choicesEl);

    this.element.appendChild(headerRow);
    this.element.appendChild(bodyWrapper);

    container.appendChild(this.element);
    this.setupEventListeners();

    return this.element;
  }

  /**
   * Show the banner with the given type and event data.
   */
  show(type: DecisionModalType, event: DecisionEventData): void {
    if (this.isShowing) {
      console.warn('[DecisionBanner] Banner already showing, ignoring rapid event');
      return;
    }

    if (!event || !('task_id' in event)) {
      console.error('[DecisionBanner] Missing required event data (task_id)');
      return;
    }

    this.currentType = type;
    this.currentEvent = event;
    this.isCollapsed = false;

    this.renderBannerContent();

    this.isShowing = true;
    if (this.element) {
      this.element.style.display = '';
    }
  }

  /**
   * Hide the banner and reset state.
   */
  hide(): void {
    if (!this.isShowing) return;

    this.isShowing = false;
    if (this.element) {
      this.element.style.display = 'none';
    }

    if (this.titleEl) this.titleEl.textContent = '';
    if (this.bodyEl) this.bodyEl.innerHTML = '';
    if (this.choicesEl) this.choicesEl.innerHTML = '';

    if (this.noteArea) {
      this.noteArea.remove();
      this.noteArea = null;
    }

    if (this.errorEl) {
      this.errorEl.remove();
      this.errorEl = null;
    }

    this.currentType = null;
    this.currentEvent = null;
    this.pendingChoice = null;
    this.requireTextForDeny = false;
    this.isSubmitting = false;
  }

  /**
   * Clean up event listeners and references
   */
  destroy(): void {
    for (const eventName of Object.keys(EVENT_NAME_TO_TYPE)) {
      window.removeEventListener(eventName, this.handleGenericEvent);
    }

    if (this.element && this.element.parentNode) {
      this.element.parentNode.removeChild(this.element);
    }

    this.element = null;
    this.titleEl = null;
    this.bodyEl = null;
    this.choicesEl = null;
    this.collapseBtn = null;
  }

  // ============================================================================
  // Private Methods
  // ============================================================================

  private setupEventListeners(): void {
    for (const eventName of Object.keys(EVENT_NAME_TO_TYPE)) {
      window.addEventListener(eventName, this.handleGenericEvent);
    }
  }

  private toggleCollapse(): void {
    this.isCollapsed = !this.isCollapsed;
    const bodyWrapper = this.element?.querySelector('.decision-banner-body') as HTMLElement | null;
    if (bodyWrapper) {
      bodyWrapper.style.display = this.isCollapsed ? 'none' : '';
    }
    if (this.collapseBtn) {
      this.collapseBtn.innerHTML = this.isCollapsed ? '&#x25B2;' : '&#x25BC;';
    }
  }

  /**
   * Render banner content based on type using the data-driven BANNER_CONFIG.
   */
  private renderBannerContent(): void {
    if (!this.titleEl || !this.bodyEl || !this.choicesEl || !this.currentType || !this.currentEvent) return;

    const config = BANNER_CONFIG[this.currentType];
    if (!config) {
      throw new Error('Unknown decision banner type: ' + this.currentType);
    }

    // Set title
    this.titleEl.textContent = config.title;

    // Build body HTML from configured fields
    const event = this.currentEvent;
    const bodyHtml = config.bodyFields
      .map((field) => {
        if (typeof field === 'string') return field;
        const value = field(event);
        return value != null ? '<p>' + value + '</p>' : '';
      })
      .filter(Boolean)
      .join('');
    this.bodyEl.innerHTML = bodyHtml;

    // Render buttons and optional note input
    const choices = this.currentEvent.choices;
    if (config.showNote && config.denyChoiceValue) {
      this.requireTextForDeny = true;
      this.pendingChoice = config.denyChoiceValue;
      this.renderChoiceButtonsFromEvent(choices, config.denyChoiceValue);
      this.showNoteInputInline(config.noteLabel || 'Please explain your reason:');
    } else {
      this.requireTextForDeny = false;
      this.renderChoiceButtonsFromEvent(choices);
    }
  }

  // ---- Button rendering ----

  /**
   * Render choice buttons from backend event.choices.
   * The first choice matching PRIMARY_ACTIONS gets the primary style.
   * If specialChoice is set, that value gets a special click handler instead.
   */
  private renderChoiceButtonsFromEvent(choices: Array<{ value: string; label: string; description?: string }>, specialChoice?: string): void {
    if (!this.choicesEl || !choices) return;

    choices.forEach((choice) => {
      const btn = document.createElement('button');
      btn.className = PRIMARY_ACTIONS.has(choice.value) ? 'modal-btn-primary' : 'modal-btn-secondary';
      btn.textContent = choice.label;
      if (choice.description) {
        btn.setAttribute('title', choice.description);
      }
      if (choice.value === specialChoice) {
        btn.addEventListener('click', () => this.handleDenyClick());
      } else {
        btn.addEventListener('click', () => this.submitDecision(choice.value));
      }
      this.choicesEl!.appendChild(btn);
    });
  }

  // ---- Deny handling (decomposition only) ----

  private showNoteInputInline(label: string): void {
    if (!this.choicesEl) return;

    const labelEl = document.createElement('label');
    labelEl.setAttribute('for', 'decision-banner-note');
    labelEl.textContent = label;
    labelEl.style.cssText = 'display: block; margin-top: 12px; margin-bottom: 6px; color: var(--text2); font-size: 0.8125rem;';

    this.noteArea = document.createElement('textarea');
    this.noteArea.id = 'decision-banner-note';
    this.noteArea.setAttribute('aria-label', 'Explanation for denial');
    this.noteArea.placeholder = 'Enter your reason here...';
    this.noteArea.style.cssText = 'display: block; width: 100%; min-height: 60px; padding: 6px; margin-bottom: 10px; background: var(--bg1); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-family: inherit; font-size: 0.8125rem; resize: vertical; box-sizing: border-box;';

    this.choicesEl.appendChild(labelEl);
    this.choicesEl.appendChild(this.noteArea);
  }

  private handleDenyClick(): void {
    if (this.requireTextForDeny) {
      if (this.noteArea) {
        this.handleNoteSubmit();
      } else {
        this.pendingChoice = 'deny';
        this.showNoteInput('Please explain why you are denying this decomposition:');
      }
    } else {
      this.submitDecision('deny');
    }
  }

  private showNoteInput(label: string): void {
    if (this.noteArea) this.noteArea.remove();
    if (this.errorEl) { this.errorEl.remove(); this.errorEl = null; }

    if (this.choicesEl) this.choicesEl.innerHTML = '';

    const labelEl = document.createElement('label');
    labelEl.setAttribute('for', 'decision-banner-note');
    labelEl.textContent = label;
    labelEl.style.cssText = 'display: block; margin-bottom: 6px; color: var(--text2); font-size: 0.8125rem;';

    this.noteArea = document.createElement('textarea');
    this.noteArea.id = 'decision-banner-note';
    this.noteArea.setAttribute('aria-label', 'Explanation for denial');
    this.noteArea.placeholder = 'Enter your reason here...';
    this.noteArea.style.cssText = 'width: 100%; min-height: 60px; padding: 6px; margin-bottom: 10px; background: var(--bg1); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-family: inherit; font-size: 0.8125rem; resize: vertical;';

    const submitBtn = document.createElement('button');
    submitBtn.className = 'modal-btn-secondary';
    submitBtn.textContent = 'Submit';
    submitBtn.addEventListener('click', () => this.handleNoteSubmit());

    this.choicesEl!.appendChild(labelEl);
    this.choicesEl!.appendChild(this.noteArea);
    this.choicesEl!.appendChild(submitBtn);

    this.noteArea.focus();
  }

  private handleNoteSubmit(): void {
    if (!this.noteArea || !this.pendingChoice) return;

    const note = this.noteArea.value.trim();

    if (!note) {
      this.showValidationError('A reason is required.');
      return;
    }

    this.submitDecision(this.pendingChoice, note);
  }

  private showValidationError(message: string): void {
    if (this.errorEl) this.errorEl.remove();

    this.errorEl = document.createElement('div');
    this.errorEl.className = 'decision-banner-error';
    this.errorEl.setAttribute('role', 'alert');
    this.errorEl.textContent = message;

    if (this.choicesEl && this.choicesEl.parentNode) {
      this.choicesEl.parentNode.insertBefore(this.errorEl, this.choicesEl);
    }

    if (this.noteArea) {
      this.noteArea.style.borderColor = 'var(--red)';
    }
  }

  // ---- Generic event handler ----

  private handleGenericEvent = (e: Event): void => {
    const customEvent = e as CustomEvent;
    if (!customEvent.detail) return;

    const eventName = e.type;
    const decisionType = EVENT_NAME_TO_TYPE[eventName];
    if (!decisionType) {
      console.warn('[DecisionBanner] Unknown event type:', eventName);
      return;
    }

    this.show(decisionType, customEvent.detail);
  };

  // ---- API submission ----

  private async submitDecision(choice: string, note?: string): Promise<void> {
    if (!this.currentEvent) return;
    if (this.isSubmitting) return;

    const taskId = (this.currentEvent as unknown as Record<string, unknown>).task_id as string;
    const apiDecisionType = this.currentType ? TYPE_TO_EVENT_NAME[this.currentType] : 'unknown';

    this.isSubmitting = true;

    try {
      const { submitDecision } = await import('../api/client');

      await submitDecision(
        taskId,
        apiDecisionType,
        choice,
        note || ''
      );

      this.hide();
    } catch (error) {
      console.error('[DecisionBanner] Submission failed:', error);
      this.isSubmitting = false;
      this.showSubmissionError(error);
      this.renderRetryButtons();
    }
  }

  private showSubmissionError(error: unknown): void {
    if (this.errorEl) this.errorEl.remove();

    let errorMessage = 'Failed to submit decision. Please try again.';
    if (error instanceof Error && 'detail' in error) {
      const detail = (error as Record<string, string | undefined>).detail;
      if (detail) errorMessage = detail;
    } else if (error instanceof Error) {
      errorMessage = error.message;
    }

    this.errorEl = document.createElement('div');
    this.errorEl.className = 'decision-banner-error';
    this.errorEl.setAttribute('role', 'alert');
    this.errorEl.textContent = errorMessage;

    if (this.choicesEl && this.choicesEl.parentNode) {
      this.choicesEl.parentNode.insertBefore(this.errorEl, this.choicesEl);
    }
  }

  private renderRetryButtons(): void {
    if (!this.choicesEl || !this.currentType || !this.currentEvent) return;
    this.choicesEl.innerHTML = '';

    const choices = (this.currentEvent as unknown as Record<string, unknown>).choices as Array<{ value: string; label: string; description?: string }> | undefined;
    if (choices && Array.isArray(choices)) {
      const config = BANNER_CONFIG[this.currentType];
      const specialChoice: string | undefined = config?.denyChoiceValue;
      this.renderChoiceButtonsFromEvent(choices, specialChoice);
    }

    // For decomposition, re-add the textarea since innerHTML cleared it
    if (this.currentType === 'decomposition') {
      const config = BANNER_CONFIG.decomposition;
      this.showNoteInputInline(config.noteLabel || 'Please explain why you are denying this decomposition:');
    }
  }
}
