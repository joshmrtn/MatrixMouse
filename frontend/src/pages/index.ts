/**
 * Pages Router
 */

import { ChannelPage } from './ChannelPage';
import { TaskPage } from './TaskPage';
import { TasksPage } from './TasksPage';
import { StatusPage } from './StatusPage';
import { SettingsPage } from './SettingsPage';

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

  switch (page) {
    case 'channel':
      new ChannelPage(params.scope || 'workspace').render(container);
      break;

    case 'task':
      if (params.id) {
        new TaskPage(params.id).render(container);
      }
      break;

    case 'tasks':
      new TasksPage().render(container);
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
