import React, { useState } from 'react';
import { Search } from 'lucide-react';

const SearchBar: React.FC<{OnQuery: (query: string) => void}> = ({ OnQuery }) => {
    const [query, setQuery] = useState('');

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
            if (e.key === 'Enter') {
                e.currentTarget.blur(); // Remove focus, which triggers onBlur -> handleCommit
            }
        };

    return (
        <div className='bg-zinc-800 hover:bg-zinc-700 transition-colors rounded-full px-6 py-3 flex items-center gap-4 w-full max-w-xl border border-zinc-600 focus-within:border-blue-500'>
            <Search 
                size={24} 
                className='text-zinc-400' 
            />
            <input 
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onBlur={() => OnQuery(query)}
                onKeyDown={handleKeyDown}
                placeholder="Search library..."
                className='bg-transparent border-none outline-none text-white text-lg w-full placeholder:text-zinc-500'
            />
        </div>
    );
};

export default SearchBar;