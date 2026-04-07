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

export class DecisionBanner {
  private element: HTMLElement | null = null;
  private titleEl: HTMLElement | null = null;
  private bodyEl: HTMLElement | null = null;
  private choicesEl: HTMLElement | null = null;
  private noteArea: HTMLTextAreaElement | null = null;
  private errorEl: HTMLElement | null = null;
  private collapseBtn: HTMLElement | null = null;

  private isShowing = false;
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
    window.removeEventListener('decomposition_confirmation_required', this.handleDecompositionEvent);
    window.removeEventListener('pr_approval_required', this.handlePREvent);
    window.removeEventListener('turn_limit_reached', this.handleTurnLimitEvent);
    window.removeEventListener('planning_turn_limit_reached', this.handlePlanningTurnLimitEvent);
    window.removeEventListener('merge_conflict_resolution_turn_limit_reached', this.handleMergeTurnLimitEvent);
    window.removeEventListener('critic_turn_limit_reached', this.handleCriticTurnLimitEvent);

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
    window.addEventListener('decomposition_confirmation_required', this.handleDecompositionEvent);
    window.addEventListener('pr_approval_required', this.handlePREvent);
    window.addEventListener('turn_limit_reached', this.handleTurnLimitEvent);
    window.addEventListener('planning_turn_limit_reached', this.handlePlanningTurnLimitEvent);
    window.addEventListener('merge_conflict_resolution_turn_limit_reached', this.handleMergeTurnLimitEvent);
    window.addEventListener('critic_turn_limit_reached', this.handleCriticTurnLimitEvent);
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
   * Render banner content based on type. Each modal renders contextual body
   * text and buttons driven by event.choices from the backend.
   */
  private renderBannerContent(): void {
    if (!this.titleEl || !this.bodyEl || !this.choicesEl) return;

    switch (this.currentType) {
      case 'decomposition':
        this.renderDecompositionBanner();
        break;
      case 'pr_approval':
        this.renderPRApprovalBanner();
        break;
      case 'turn_limit':
        this.renderTurnLimitBanner();
        break;
      case 'planning_turn_limit':
        this.renderPlanningTurnLimitBanner();
        break;
      case 'merge_turn_limit':
        this.renderMergeTurnLimitBanner();
        break;
      case 'critic_turn_limit':
        this.renderCriticTurnLimitBanner();
        break;
      default: {
        const _exhaustiveCheck: never = this.currentType;
        throw new Error('Unknown decision banner type: ' + _exhaustiveCheck);
      }
    }
  }

  // ---- Decomposition ----

  private renderDecompositionBanner(): void {
    if (!this.titleEl || !this.bodyEl || !this.choicesEl || !this.currentEvent) return;

    const event = this.currentEvent as DecompositionEventData;

    this.titleEl.textContent = '\u26A0\uFE0F Decision Required: Task Decomposition';
    this.bodyEl.innerHTML =
      '<p>Agent wants to split <strong>' + escapeHtml(event.task_title || event.task_id) + '</strong> into subtasks.</p>' +
      '<p>Depth: <strong>' + (event.current_depth ?? 0) + '</strong> / <strong>' + (event.allowed_depth ?? 3) + '</strong> allowed</p>';

    this.requireTextForDeny = true;
    this.pendingChoice = 'deny';

    this.renderChoiceButtonsFromEvent(event.choices, 'deny');
    this.showNoteInputInline('Please explain why you are denying this decomposition:');
  }

  // ---- PR Approval ----

  private renderPRApprovalBanner(): void {
    if (!this.titleEl || !this.bodyEl || !this.choicesEl || !this.currentEvent) return;

    const event = this.currentEvent as PRApprovalEventData;

    this.titleEl.textContent = '\u26A0\uFE0F Decision Required: Pull Request Approval';
    this.bodyEl.innerHTML =
      '<p><strong>' + escapeHtml(event.task_title || event.task_id) + '</strong></p>' +
      '<p>Branch: <code>' + escapeHtml(event.branch) + '</code> &rarr; <code>' + escapeHtml(event.parent_branch) + '</code></p>' +
      '<p>Repo: <code>' + escapeHtml(event.repo) + '</code></p>';

    this.renderChoiceButtonsFromEvent(event.choices);
  }

  // ---- Turn Limit (generic - Coder, Writer) ----

  private renderTurnLimitBanner(): void {
    if (!this.titleEl || !this.bodyEl || !this.choicesEl || !this.currentEvent) return;

    const event = this.currentEvent as TurnLimitEventData;

    this.titleEl.textContent = '\u26A0\uFE0F Decision Required: Turn Limit Reached';
    this.bodyEl.innerHTML =
      '<p><strong>' + escapeHtml(event.task_title || event.task_id) + '</strong></p>' +
      '<p>Role: ' + escapeHtml(event.role || 'unknown') + '</p>' +
      '<p>Turns: <strong>' + event.turns_taken + '</strong> / <strong>' + event.turn_limit + '</strong></p>';

    this.renderChoiceButtonsFromEvent(event.choices);
  }

  // ---- Planning Turn Limit (Manager) ----

  private renderPlanningTurnLimitBanner(): void {
    if (!this.titleEl || !this.bodyEl || !this.choicesEl || !this.currentEvent) return;

    const event = this.currentEvent as PlanningTurnLimitEventData;

    this.titleEl.textContent = '\u26A0\uFE0F Decision Required: Planning Turn Limit';
    this.bodyEl.innerHTML =
      '<p><strong>' + escapeHtml(event.task_title || event.task_id) + '</strong></p>' +
      '<p>Turns: <strong>' + event.turns_taken + '</strong></p>';

    this.renderChoiceButtonsFromEvent(event.choices);
  }

  // ---- Merge Turn Limit (Merge agent) ----

  private renderMergeTurnLimitBanner(): void {
    if (!this.titleEl || !this.bodyEl || !this.choicesEl || !this.currentEvent) return;

    const event = this.currentEvent as MergeTurnLimitEventData;

    let resolvedText = '';
    if (event.resolved_so_far && event.resolved_so_far.length > 0) {
      resolvedText = '<p>Resolved so far: ' + escapeHtml(
        event.resolved_so_far.map((r: { file: string; resolution: string }) => r.file).join(', ')
      ) + '</p>';
    }

    this.titleEl.textContent = '\u26A0\uFE0F Decision Required: Merge Turn Limit';
    this.bodyEl.innerHTML =
      '<p><strong>' + escapeHtml(event.task_title || event.task_id) + '</strong></p>' +
      '<p>Turns: <strong>' + event.turns_taken + '</strong></p>' +
      '<p>Parent: <code>' + escapeHtml(event.parent_branch) + '</code></p>' +
      resolvedText;

    this.renderChoiceButtonsFromEvent(event.choices);
  }

  // ---- Critic Turn Limit ----

  private renderCriticTurnLimitBanner(): void {
    if (!this.titleEl || !this.bodyEl || !this.choicesEl || !this.currentEvent) return;

    const event = this.currentEvent as CriticTurnLimitEventData;

    this.titleEl.textContent = '\u26A0\uFE0F Decision Required: Critic Turn Limit';
    this.bodyEl.innerHTML =
      '<p><strong>' + escapeHtml(event.task_title || event.task_id) + '</strong></p>' +
      '<p>Turns: <strong>' + event.turns_taken + '</strong> / <strong>' + event.critic_max_turns + '</strong></p>' +
      '<p>Reviewed task: <code>' + escapeHtml(event.reviewed_task_id) + '</code></p>';

    this.renderChoiceButtonsFromEvent(event.choices);
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
      this.choicesEl.appendChild(btn);
    });
  }

  // ---- Deny handling (decomposition only) ----

  private showNoteInputInline(label: string): void {
    if (!this.choicesEl) return;

    this.pendingChoice = 'deny';

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

    this.choicesEl.appendChild(labelEl);
    this.choicesEl.appendChild(this.noteArea);
    this.choicesEl.appendChild(submitBtn);

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

  // ---- Event handlers ----

  private handleDecompositionEvent = (e: Event): void => {
    const event = e as CustomEvent;
    if (event.detail) {
      this.show('decomposition', event.detail);
    }
  };

  private handlePREvent = (e: Event): void => {
    const event = e as CustomEvent;
    if (event.detail) {
      this.show('pr_approval', event.detail);
    }
  };

  private handleTurnLimitEvent = (e: Event): void => {
    const event = e as CustomEvent;
    if (event.detail) {
      this.show('turn_limit', event.detail);
    }
  };

  private handlePlanningTurnLimitEvent = (e: Event): void => {
    const event = e as CustomEvent;
    if (event.detail) {
      this.show('planning_turn_limit', event.detail);
    }
  };

  private handleMergeTurnLimitEvent = (e: Event): void => {
    const event = e as CustomEvent;
    if (event.detail) {
      this.show('merge_turn_limit', event.detail);
    }
  };

  private handleCriticTurnLimitEvent = (e: Event): void => {
    const event = e as CustomEvent;
    if (event.detail) {
      this.show('critic_turn_limit', event.detail);
    }
  };

  // ---- API submission ----

  private async submitDecision(choice: string, note?: string): Promise<void> {
    if (!this.currentEvent) return;
    if (this.isSubmitting) return;

    const taskId = (this.currentEvent as any).task_id;

    const decisionTypeMap: Record<string, string> = {
      decomposition: 'decomposition_confirmation_required',
      pr_approval: 'pr_approval_required',
      turn_limit: 'turn_limit_reached',
      planning_turn_limit: 'planning_turn_limit_reached',
      merge_turn_limit: 'merge_conflict_resolution_turn_limit_reached',
      critic_turn_limit: 'critic_turn_limit_reached',
    };
    const apiDecisionType = (this.currentType && decisionTypeMap[this.currentType]) || 'unknown';

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
      errorMessage = (error as any).detail;
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

    const choices = (this.currentEvent as any).choices;
    if (choices && Array.isArray(choices)) {
      const specialChoice = this.currentType === 'decomposition' ? 'deny' : undefined;
      this.renderChoiceButtonsFromEvent(choices, specialChoice);
    }

    // For decomposition, re-add the textarea since innerHTML cleared it
    if (this.currentType === 'decomposition') {
      this.showNoteInputInline('Please explain why you are denying this decomposition:');
    }
  }
}
