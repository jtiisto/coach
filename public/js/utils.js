/**
 * Utility functions for Coach
 */

/**
 * Format a Date object as YYYY-MM-DD string in LOCAL timezone
 */
export function formatDateLocal(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

/**
 * Get today's date as YYYY-MM-DD string in LOCAL timezone
 */
export function getToday() {
    return formatDateLocal(new Date());
}

/**
 * Get current UTC time as ISO-8601 string
 */
export function getUtcNow() {
    return new Date().toISOString();
}

/**
 * Generate a UUID v4
 * Falls back to manual generation for insecure contexts (HTTP on mobile)
 */
export function generateId() {
    if (crypto.randomUUID) {
        try {
            return crypto.randomUUID();
        } catch (e) {
            // Falls through to manual generation
        }
    }
    // Fallback for insecure contexts
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

/**
 * Parse a YYYY-MM-DD string as a local date (midnight in local timezone)
 */
export function parseLocalDate(dateStr) {
    const [year, month, day] = dateStr.split('-').map(Number);
    return new Date(year, month - 1, day);
}

/**
 * Format date for display (e.g., "Mon", "Feb 2")
 */
export function formatDateShort(dateStr) {
    const date = parseLocalDate(dateStr);
    return {
        day: date.toLocaleDateString('en-US', { weekday: 'short' }),
        num: date.getDate()
    };
}

/**
 * Get an array of dates centered around today
 */
export function getDateRange(centerDate, daysAround = 3) {
    const dates = [];
    const center = parseLocalDate(centerDate);

    for (let i = -daysAround; i <= daysAround; i++) {
        const date = new Date(center);
        date.setDate(date.getDate() + i);
        dates.push(formatDateLocal(date));
    }

    return dates;
}

/**
 * Check if a date is today
 */
export function isToday(dateStr) {
    return dateStr === getToday();
}

/**
 * Check if a date is in the past (before today)
 */
export function isPast(dateStr) {
    return dateStr < getToday();
}

/**
 * Check if a date is in the future (after today)
 */
export function isFuture(dateStr) {
    return dateStr > getToday();
}

/**
 * Format exercise target for display
 */
export function formatTarget(exercise) {
    switch (exercise.type) {
        case 'strength':
        case 'circuit':
            return `${exercise.target_sets} x ${exercise.target_reps}`;
        case 'duration':
            return `${exercise.target_duration_min} min`;
        case 'checklist':
            return `${exercise.items?.length || 0} items`;
        case 'weighted_time':
            return `${exercise.target_duration_sec || 60}s`;
        case 'interval':
            return `${exercise.rounds} rounds`;
        default:
            return '';
    }
}

/**
 * Check if an exercise is completed based on log data
 */
export function isExerciseCompleted(exercise, logData) {
    if (!logData) return false;

    switch (exercise.type) {
        case 'checklist':
            const completed = logData.completed_items || [];
            return completed.length === (exercise.items?.length || 0);
        case 'strength':
            const sets = logData.sets || [];
            return sets.length >= (exercise.target_sets || 1);
        case 'duration':
            return logData.duration_min != null;
        default:
            return logData.completed === true;
    }
}

/**
 * Deep clone an object
 */
export function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}
