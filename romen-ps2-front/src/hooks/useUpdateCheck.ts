import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';

export interface Release {
    version: string;
    name: string;
    notes: string;
    published_at: string | null;
    url: string | null;
    prerelease: boolean;
    download_url: string | null;
    download_name: string | null;
    download_size: number | null;
    download_count: number | null;
}

export interface UpdateStatus {
    status: 'success' | 'error';
    message?: string;
    current_version: string;
    update_available: boolean;
    repo?: string;
    latest?: Release;
}

/**
 * Asks the server to compare the running build against the latest GitHub
 * release. The server caches the API response for an hour, so mounting this
 * hook is cheap; `check(true)` forces a fresh call for the "check again" button.
 */
export function useUpdateCheck(enabled: boolean = true) {
    const [update, setUpdate] = useState<UpdateStatus | null>(null);
    const [loading, setLoading] = useState(false);

    const check = useCallback(async (force: boolean = false) => {
        setLoading(true);
        try {
            const response = await axios.get<UpdateStatus>('/updates', {
                params: force ? { force: true } : undefined,
            });
            setUpdate(response.data);
            return response.data;
        } catch (error) {
            console.error('Failed to check for updates: ', error);
            const failed: UpdateStatus = {
                status: 'error',
                message: 'Could not reach the server.',
                current_version: update?.current_version ?? '',
                update_available: false,
            };
            setUpdate(failed);
            return failed;
        } finally {
            setLoading(false);
        }
    }, [update?.current_version]);

    useEffect(() => {
        if (enabled) check();
        // Only re-run when the caller flips `enabled`; `check` is stable enough here.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [enabled]);

    return { update, loading, check };
}
