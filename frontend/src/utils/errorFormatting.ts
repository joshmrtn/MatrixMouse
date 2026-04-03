/**
 * Format API error messages for user display
 */

/**
 * Format an API error into a user-friendly message
 * @param error - The error to format (typically from API call)
 * @returns A user-friendly error message
 */
export function formatApiError(error: unknown): string {
  if (error instanceof Error) {
    // Network errors
    if (error.message.includes('Failed to fetch')) {
      return 'Network error: Unable to connect to server. Please check your connection and try again.';
    }
    
    // API error with detail
    const match = error.message.match(/API Error:?\s*(.+)/i);
    if (match && match[1]) {
      return `Error: ${match[1]}`;
    }
    
    // Generic error
    return error.message;
  }
  
  // Unknown error type
  return 'An unexpected error occurred';
}
