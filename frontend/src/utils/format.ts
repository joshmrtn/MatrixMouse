/**
 * Markdown renderer for agent content
 * Handles: fenced code blocks, inline code, headers, bold, italic, lists
 * 
 * Security: Escapes all HTML first, then processes markdown syntax.
 * This prevents XSS attacks via prompt injection.
 */

/**
 * Render markdown to HTML
 */
export function renderMarkdown(raw: string): string {
  const placeholders: string[] = [];

  // Helper: stash HTML and return placeholder
  function stash(html: string): string {
    const token = `\x00${placeholders.length}\x00`;
    placeholders.push(html);
    return token;
  }

  // Helper: restore placeholders
  function restore(s: string): string {
    return s.replace(/\x00(\d+)\x00/g, (_, i) => placeholders[+i]);
  }

  let s = raw;

  // 1. Fenced code blocks - extract and escape BEFORE main processing
  s = s.replace(/```([^\n`]*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const cls = lang.trim() ? ` class="lang-${escapeHtml(lang.trim())}"` : '';
    return stash(`<pre><code${cls}>${escapeHtml(code.trimEnd())}</code></pre>`);
  });

  // 2. Inline code - extract and escape BEFORE main processing
  s = s.replace(/`([^`\n]+)`/g, (_, code) => stash(`<code>${escapeHtml(code)}</code>`));

  // 3. NOW escape all remaining text (headers, lists, bold, italic content)
  // Split by placeholders to avoid escaping them
  const parts = s.split(/(\x00\d+\x00)/g);
  s = parts.map((part, i) => {
    // Don't escape placeholders
    if (part.match(/^\x00\d+\x00$/)) return part;
    return escapeHtml(part);
  }).join('');

  // Process line by line for block elements
  const lines = s.split('\n');
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i]!;

    // 3. ATX headers
    const hm = line.match(/^(#{1,3})\s+(.+)/);
    if (hm) {
      const level = hm[1]!.length;
      out.push(`<h${level}>${inlinePass(hm[2]!)}</h${level}>`);
      i++;
      continue;
    }

    // 4. Unordered list
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i]!)) {
        items.push(`<li>${inlinePass(lines[i]!.replace(/^[-*]\s+/, ''))}</li>`);
        i++;
      }
      out.push(`<ul>${items.join('')}</ul>`);
      continue;
    }

    // 5. Ordered list
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i]!)) {
        items.push(`<li>${inlinePass(lines[i]!.replace(/^\d+\.\s+/, ''))}</li>`);
        i++;
      }
      out.push(`<ol>${items.join('')}</ol>`);
      continue;
    }

    // 6. Blank line
    if (line.trim() === '') {
      out.push('<br>');
      i++;
      continue;
    }

    // 7. Plain line
    out.push(`${inlinePass(line)}<br>`);
    i++;
  }

  return restore(out.join(''));
}

/**
 * Inline markdown rules (bold, italic)
 */
function inlinePass(s: string): string {
  // Bold
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Italic (underscore)
  s = s.replace(/(?<![_\w])_([^_]+)_(?![_\w])/g, '<em>$1</em>');
  // Italic (asterisk)
  s = s.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
  return s;
}

/**
 * Escape HTML special characters
 */
export function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Format status for display (snake_case → Title Case)
 */
export function formatStatus(status: string): string {
  return status
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Format role for display (capitalize first letter)
 */
export function formatRole(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}
