import { Settings } from 'lucide-react';
import React from 'react';
import SearchBar from './SearchBar';

const Header : React.FC<{ setSettingsModalOpen: (open: boolean) => void; OnQuery : (query: string) => void}> = ({ setSettingsModalOpen, OnQuery }) => {
    return (
        <header className="sticky top-0 z-50 w-full bg-zinc-900 shadow-md flex items-center p-5">
            
            {/* Left Section: Logo and Title */}
            <div className="flex items-center space-x-4 flex-1">
                <img src="/img/romen_logo.png" alt="Logo" 
                className="w-16 h-auto object-contain" />
                <div className="hidden sm:block">
                    <h1 className="text-2xl font-bold leading-tight">Romen</h1>
                    <p className="text-xs text-zinc-400">PlayStation 2 ROM Manager</p>
                </div>
            </div>

            {/* Middle Section: Search Bar (Centered) */}
            <div className="flex-2 flex justify-center">
                <div className="w-full max-w-xl">
                    <SearchBar OnQuery={OnQuery} />
                </div>
            </div>

            {/* Right Section: Settings */}
            <div className="flex-1 flex justify-end">
                <Settings 
                    className="text-zinc-500 scale-125 cursor-pointer hover:scale-130 hover:text-sky-600 transition-all duration-200" 
                    onClick={() => setSettingsModalOpen(true)} 
                />
            </div>

        </header>
    );
}

export default Header;