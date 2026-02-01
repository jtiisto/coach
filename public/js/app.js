/**
 * Coach - Main App Component
 */
import { h, render } from 'preact';
import { useState, useEffect } from 'preact/hooks';
import { effect } from '@preact/signals';
import htm from 'htm';

import {
    isLoading,
    selectedDate,
    workoutPlans,
    workoutLogs,
    initializeStore
} from './store.js';
import { getToday } from './utils.js';

import { Header } from './components/Header.js';
import { CalendarPicker } from './components/CalendarPicker.js';
import { WorkoutView } from './components/WorkoutView.js';
import { Notifications } from './components/Notifications.js';

const html = htm.bind(h);

function App() {
    const [loading, setLoading] = useState(true);
    const [date, setDate] = useState(selectedDate.value);
    const [plans, setPlans] = useState({});
    const [logs, setLogs] = useState({});

    // Subscribe to signals
    useEffect(() => {
        const dispose = effect(() => {
            setLoading(isLoading.value);
            setDate(selectedDate.value);
            setPlans({ ...workoutPlans.value });
            setLogs({ ...workoutLogs.value });
        });
        return dispose;
    }, []);

    // Initialize store on mount
    useEffect(() => {
        initializeStore();
    }, []);

    const currentPlan = plans[date] || null;
    const currentLog = logs[date] || null;
    const isEditable = date === getToday();

    return html`
        <div class="app">
            <${Header} />
            <${CalendarPicker} plans=${plans} logs=${logs} />
            <main class="main-content">
                ${loading ? html`
                    <div class="loading">
                        <div class="loading-spinner"></div>
                        <span>Loading...</span>
                    </div>
                ` : html`
                    <${WorkoutView}
                        date=${date}
                        plan=${currentPlan}
                        log=${currentLog}
                        isEditable=${isEditable}
                    />
                `}
            </main>
            <${Notifications} />
        </div>
    `;
}

// Mount the app
render(html`<${App} />`, document.getElementById('app'));
