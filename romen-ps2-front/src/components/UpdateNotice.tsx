import React from 'react';
import { ArrowUpCircle, CheckCircle2, CloudOff, Download, ExternalLink, RefreshCw, AlertTriangle, Loader2, X } from 'lucide-react';
import { useUpdateCheck } from '../hooks/useUpdateCheck';
import { useUpdateInstall } from '../hooks/useUpdateInstall';

interface UpdateNoticeProps {
    /** Re-checks whenever this flips true, so opening Settings refreshes it. */
    active?: boolean;
}

function PrettyPrintSize(bytes?: number | null) {
    if (!bytes) return '';
    return `${(bytes / (1024 ** 2)).toFixed(1)} MB`;
}

function PrettyPrintDate(iso?: string | null) {
    if (!iso) return '';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

const UpdateNotice: React.FC<UpdateNoticeProps> = ({ active = true }) => {
    const { update, loading, check } = useUpdateCheck(active);
    const { state, phase, error, start, dismiss } = useUpdateInstall(active);

    const latest = update?.latest;
    const outdated = !!update?.update_available && !!latest;
    const failed = update?.status === 'error';

    const busy = phase === 'installing' || phase === 'reconnecting';
    const result = state?.last_result;

    // The install replaces ISObe's own files and restarts it, so it is always
    // an explicit choice -- never something that happens in the background.
    const handleInstall = async () => {
        if (!latest) return;
        const confirmed = confirm(
            `Update ISObe to ${latest.version}?\n\n` +
            `The current version is backed up first, and ISObe restarts when it finishes. ` +
            `Your library, settings and memory cards are not touched.`
        );
        if (!confirmed) return;
        await start();
    };

    return (
        <div className="flex flex-col space-y-3">
            <div className="flex flex-row items-center justify-between">
                <div className="flex flex-row items-center space-x-4">
                    <ArrowUpCircle size={24} className="text-white" />
                    <p className="font-semibold text-xl text-zinc-100">Updates</p>
                </div>

                <button
                    onClick={() => check(true)}
                    disabled={loading}
                    title="Check for updates"
                    className="flex items-center space-x-2 text-sm text-zinc-400 hover:text-sky-500 disabled:text-zinc-600 transition-colors cursor-pointer disabled:cursor-default"
                >
                    <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
                    <span>{loading ? 'Checking…' : 'Check now'}</span>
                </button>
            </div>

            {/* Outcome of a finished install */}
            {result && !busy && (
                <div className={`flex items-start space-x-2 rounded-lg p-3 text-sm border ${
                    result.status === 'success'
                        ? 'bg-green-600/10 border-green-600/30 text-green-400'
                        : 'bg-red-600/10 border-red-600/30 text-red-400'
                }`}>
                    {result.status === 'success'
                        ? <CheckCircle2 size={18} className="shrink-0 mt-0.5" />
                        : <AlertTriangle size={18} className="shrink-0 mt-0.5" />}
                    <span className="flex-1">{result.message}</span>
                    <button onClick={dismiss} className="shrink-0 text-zinc-500 hover:text-white transition-colors">
                        <X size={16} />
                    </button>
                </div>
            )}

            {/* Something went wrong before the install could finish */}
            {error && !result && (
                <div className="flex items-start space-x-2 bg-red-600/10 border border-red-600/30 text-red-400 rounded-lg p-3 text-sm">
                    <AlertTriangle size={18} className="shrink-0 mt-0.5" />
                    <span className="flex-1">{error}</span>
                    <button onClick={dismiss} className="shrink-0 text-zinc-500 hover:text-white transition-colors">
                        <X size={16} />
                    </button>
                </div>
            )}

            {/* In progress */}
            {busy && (
                <div className="bg-sky-950/40 border border-sky-800 rounded-xl p-4 space-y-3">
                    <div className="flex items-center space-x-2 text-sky-300">
                        <Loader2 size={18} className="animate-spin" />
                        <span className="font-semibold">
                            {phase === 'reconnecting' ? 'Restarting ISObe...' : `Updating to ${state?.target_version ?? latest?.version ?? ''}`}
                        </span>
                    </div>
                    <div className="h-2 w-full bg-zinc-900 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-sky-500 rounded-full transition-all duration-300"
                            style={{ width: `${phase === 'reconnecting' ? 100 : (state?.progress ?? 0)}%` }}
                        />
                    </div>
                    <p className="text-xs text-zinc-400">
                        {phase === 'reconnecting'
                            ? 'Waiting for ISObe to come back. This page reloads on its own.'
                            : (state?.message || 'Working...')}
                    </p>
                </div>
            )}

            <div className="pl-2">
                <p className="text-zinc-400 font-semibold">
                    Installed: <span className="text-zinc-200 font-normal">
                        v{update?.current_version || '—'}
                    </span>
                </p>

                {/* Up to date */}
                {!loading && !failed && !outdated && update && !busy && (
                    <p className="flex items-center space-x-2 text-green-400 text-sm mt-1">
                        <CheckCircle2 size={16} />
                        <span>You're running the latest release.</span>
                    </p>
                )}

                {/* Check failed (offline, rate limited, no releases yet) */}
                {!loading && failed && (
                    <p className="flex items-center space-x-2 text-amber-300 text-sm mt-1">
                        <CloudOff size={16} />
                        <span>{update?.message || 'Could not check for updates.'}</span>
                    </p>
                )}
            </div>

            {/* Update available */}
            {outdated && !busy && (
                <div className="bg-sky-950/40 border border-sky-800 rounded-xl p-4 space-y-3">
                    <div className="flex items-baseline justify-between gap-3">
                        <p className="font-bold text-lg text-sky-300 truncate" title={latest.name}>
                            {latest.name}
                        </p>
                        <p className="text-xs text-zinc-400 shrink-0">{PrettyPrintDate(latest.published_at)}</p>
                    </div>

                    {latest.notes && (
                        <p className="text-sm text-zinc-300 whitespace-pre-line line-clamp-6 max-h-32 overflow-y-auto">
                            {latest.notes}
                        </p>
                    )}

                    <div className="flex flex-row items-center flex-wrap gap-3">
                        <button
                            onClick={handleInstall}
                            className="flex items-center space-x-2 bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-2 rounded-xl transition-colors cursor-pointer"
                        >
                            <ArrowUpCircle size={20} />
                            <span>Update &amp; Restart {PrettyPrintSize(latest.download_size)}</span>
                        </button>

                        {latest.download_url && (
                            <a
                                href={latest.download_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                title="Download the zip and install it yourself"
                                className="flex items-center space-x-1 text-sm text-zinc-400 hover:text-sky-400 transition-colors"
                            >
                                <Download size={14} />
                                <span>Download manually</span>
                            </a>
                        )}
                        {latest.url && (
                            <a
                                href={latest.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center space-x-1 text-sm text-zinc-400 hover:text-sky-400 transition-colors"
                            >
                                <span>Release notes</span>
                                <ExternalLink size={14} />
                            </a>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default UpdateNotice;
