import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';

export interface VMC {
    name: string;
    filename: string;
    path: string;
    size: number | null;
    size_mb: number | null;
    free_bytes: number | null;
    valid: boolean;
    reason: string | null;
    assigned_to: string[];
}

export interface VMCSaveFile {
    name: string;
    size: number;
}

export interface VMCSave {
    folder: string;
    serial: string | null;
    title: string | null;
    icon_title: string | null;
    size: number;
    file_count: number;
    files: VMCSaveFile[];
    modified: string | null;
    created: string | null;
    cover_url: string | null;
}

export interface VMCContents {
    name: string;
    size: number | null;
    size_mb: number | null;
    free_bytes: number | null;
    saves: VMCSave[];
}

export interface VMCSettings {
    auto_provision: boolean;
    default_size_mb: number;
}

export const useVMCs = (active: boolean) => {
    const [vmcs, setVmcs] = useState<VMC[]>([]);
    const [sizes, setSizes] = useState<number[]>([8, 16, 32, 64]);
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState(false);

    const refresh = useCallback(async () => {
        setLoading(true);
        try {
            const response = await axios.get('/vmc');
            setVmcs(response.data.vmcs ?? []);
            if (response.data.sizes) setSizes(response.data.sizes);
        } catch (error) {
            console.error('Failed to fetch VMCs: ', error);
            setVmcs([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (active) refresh();
    }, [active, refresh]);

    // Formatting a card is a disk write of up to 64MB, so callers get a `busy`
    // flag to disable the controls while it runs.
    const createVMC = async (name: string, sizeMb: number): Promise<string | null> => {
        setBusy(true);
        try {
            const response = await axios.post('/vmc', { name, size_mb: sizeMb });
            if (response.data.status !== 'success') return response.data.message ?? 'Failed to create card.';
            await refresh();
            return null;
        } catch (error) {
            console.error(error);
            return 'Failed to reach server.';
        } finally {
            setBusy(false);
        }
    };

    const deleteVMC = async (name: string): Promise<string | null> => {
        setBusy(true);
        try {
            const response = await axios.delete(`/vmc/${encodeURIComponent(name)}`);
            if (response.data.status !== 'success') return response.data.message ?? 'Failed to delete card.';
            await refresh();
            return null;
        } catch (error) {
            console.error(error);
            return 'Failed to reach server.';
        } finally {
            setBusy(false);
        }
    };

    // Importing converts a whole card, so it shares the `busy` flag that keeps
    // the create and delete controls disabled while a card is being written.
    const importVMC = async (file: File, name: string, overwrite = false): Promise<string | null> => {
        setBusy(true);
        try {
            const form = new FormData();
            form.append('file', file);
            if (name) form.append('name', name);
            form.append('overwrite', String(overwrite));
            const response = await axios.post('/vmc/import', form);
            if (response.data.status !== 'success') return response.data.message ?? 'Failed to import card.';
            await refresh();
            return null;
        } catch (error) {
            console.error(error);
            return 'Failed to reach server.';
        } finally {
            setBusy(false);
        }
    };

    return { vmcs, sizes, loading, busy, refresh, createVMC, deleteVMC, importVMC };
};

export const browseVMC = async (name: string): Promise<VMCContents> => {
    const response = await axios.get(`/vmc/${encodeURIComponent(name)}/saves`);
    if (response.data.status !== 'success') {
        throw new Error(response.data.message ?? 'Could not read that card.');
    }
    return response.data;
};

// The browser does the downloading; this only builds the URL it points at.
export const exportURL = (name: string, format: 'raw' | 'pcsx2') =>
    `/vmc/${encodeURIComponent(name)}/export?fmt=${format}`;

export const assignVMC = async (serial: string, name: string, slot: number) => {
    const response = await axios.post(`/library/${serial}/vmc`, { name, slot });
    return response.data;
};

export const unassignVMC = async (serial: string, slot: number) => {
    const response = await axios.delete(`/library/${serial}/vmc/${slot}`);
    return response.data;
};

export const fetchAssignments = async (serial: string): Promise<Record<string, string | null>> => {
    const response = await axios.get(`/library/${serial}/vmc`);
    return response.data.slots ?? {};
};

export const formatBytes = (bytes: number | null | undefined): string => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
};
