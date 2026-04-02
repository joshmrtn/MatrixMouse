/**
 * Pages Router
 */

import { ChannelPage } from './ChannelPage';
import { TaskPage } from './TaskPage';
import { TasksPage } from './TasksPage';
import { StatusPage } from './StatusPage';
import { SettingsPage } from './SettingsPage';
import { CreateTaskPage } from './CreateTaskPage';

/**
 * Render the appropriate page based on route
 */
export function renderRouter(
  page: string,
  params: Record<string, string>,
  container: HTMLElement
): void {
  // Clear container
  container.innerHTML = '';

  // Default params to empty object if undefined
  const safeParams = params || {};

  switch (page) {
    case 'channel':
      new ChannelPage(safeParams.scope || 'workspace').render(container);
      break;

    case 'task':
      if (safeParams.id) {
        new TaskPage(safeParams.id).render(container);
      }
      break;

    case 'tasks':
      new TasksPage().render(container);
      break;

    case 'task-new':  // NEW route for task creation form
      new CreateTaskPage().render(container);
      break;

    case 'dashboard':
      new StatusPage().render(container);
      break;

    case 'settings':
      new SettingsPage().render(container);
      break;

    default:
      // Default to workspace channel
      new ChannelPage('workspace').render(container);
  }
}
