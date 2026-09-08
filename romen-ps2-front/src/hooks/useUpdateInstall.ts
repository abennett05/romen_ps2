import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';

export interface InstallResult {
    status: 'success' | 'error';
    message: string;
    from_version?: string;
    to_version?: string;
    rolled_back?: boolean;
}

export interface InstallState {
    status: 'idle' | 'downloading' | 'verifying' | 'staging' | 'restarting' | 'error';
    progress: number;
    message: string;
    target_version: string | null;
    current_version: string;
    last_result: InstallResult | null;
}

/** What the UI is doing, which is not quite the same as what the server reports. */
export type InstallPhase = 'idle' | 'installing' | 'reconnecting' | 'done' | 'failed';

const POLL_INTERVAL_MS = 1000;
const RECONNECT_TIMEOUT_MS = 3 * 60 * 1000;

/**
 * Drives an in-app update: starts the install, follows its progress, and then
 * waits out the restart. Nothing here runs on its own -- `start()` is only
 * called from the button, and the server refuses to install without it.
 */
export function useUpdateInstall(active: boolean) {
    const [state, setState] = useState<InstallState | null>(null);
    const [phase, setPhase] = useState<InstallPhase>('idle');
    const [error, setError] = useState<string | null>(null);

    const timer = useRef<number | null>(null);
    const startedAt = useRef<number | null>(null);

    const stopPolling = () => {
        if (timer.current !== null) {
            window.clearInterval(timer.current);
            timer.current = null;
        }
    };

    // Read the outcome of a previous install once, on open.
    useEffect(() => {
        if (!active) return;
        axios.get<InstallState>('/updates/install/status')
            .then(({ data }) => {
                setState(data);
                // An install that finished while the page was away still has a
                // result on disk; surface it rather than silently discarding it.
                if (data.last_result && phase === 'idle') {
                    setPhase(data.last_result.status === 'success' ? 'done' : 'failed');
                }
            })
            .catch(() => { /* server not up yet; the banner just stays hidden */ });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active]);

    useEffect(() => stopPolling, []);

    const poll = useCallback(async () => {
        try {
            const { data } = await axios.get<InstallState>('/updates/install/status', { timeout: 4000 });
            setState(data);

            // The server clears the previous result when an install starts, so
            // any result we see now belongs to the install we just kicked off.
            // Keying off this rather than off seeing the transient 'restarting'
            // status matters: a fast install can finish between two polls, and
            // waiting to observe a state we may never see would hang here.
            if (data.last_result) {
                stopPolling();
                if (data.last_result.status === 'success') {
                    setPhase('done');
                    // Reload so the page matches the version now running.
                    window.setTimeout(() => window.location.reload(), 1200);
                } else {
                    setError(data.last_result.message || 'The update failed.');
                    setPhase('failed');
                }
                return;
            }

            if (data.status === 'error') {
                stopPolling();
                setError(data.message || 'The update failed.');
                setPhase('failed');
                return;
            }

            if (data.status === 'restarting') {
                setPhase('reconnecting');
            }
        } catch {
            // Expected while the server is down: it is being replaced.
            setPhase('reconnecting');
            if (startedAt.current !== null &&
                Date.now() - startedAt.current > RECONNECT_TIMEOUT_MS) {
                stopPolling();
                setError('ISObe did not come back after the update. Check the terminal it was started from.');
                setPhase('failed');
            }
        }
    }, []);

    useEffect(() => {
        if (phase !== 'installing' && phase !== 'reconnecting') return;
        stopPolling();
        timer.current = window.setInterval(poll, POLL_INTERVAL_MS);
        return stopPolling;
    }, [phase, poll]);

    const start = useCallback(async () => {
        setError(null);
        startedAt.current = Date.now();
        // Drop any banner from a previous install; the server has cleared its
        // copy, so leaving ours would immediately look like this one finished.
        setState((previous) => (previous ? { ...previous, last_result: null } : previous));
        try {
            const { data } = await axios.post('/updates/install');
            if (data.status !== 'success') {
                setError(data.message || 'Could not start the update.');
                setPhase('failed');
                return false;
            }
            setPhase('installing');
            return true;
        } catch {
            setError('Could not reach the server.');
            setPhase('failed');
            return false;
        }
    }, []);

    const dismiss = useCallback(async () => {
        setPhase('idle');
        setError(null);
        try {
            await axios.post('/updates/install/dismiss');
        } catch { /* the banner is already gone locally */ }
        setState((previous) => (previous ? { ...previous, last_result: null } : previous));
    }, []);

    return { state, phase, error, start, dismiss };
}
