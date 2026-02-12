import { useEffect, useState } from 'react';
import Grid from './components/Grid'
import Header from './components/Header'
import AddGameModal from './components/modals/AddGameModal';
import SettingsModal from './components/modals/SettingsModal';
import GameViewModal from './components/modals/GameViewModal';
import IconButton from './components/IconButton';
import { useGameUploads } from './hooks/useGameUploads';
import axios from 'axios';

// Icons
import { Plus } from 'lucide-react';

export interface Game {
  serial: string;
  title: string;
  size: number;
  cover_url: string;
}

export interface StorageDevice {
  label: string;
  file_system: string;
  space_free: number;
  total_space: number;
  path: string;
}

function App() {
  const [games, setGames] = useState<Game[]>([]);
  const [selectedGame, setSelectedGame] = useState<Game | null>(null);
  const [ gameQuery, setGameQuery ] = useState<string | null>(null);
  const [gameModalOpen, setGameModalOpen] = useState(false);
  const [storageDevice, setStorageDevice] = useState<StorageDevice | null>(null);
  const [settingsModalOpen, setSettingsModalOpen] = useState(false);
  const { queue, uploadFiles, removeFile, clearCompleted } = useGameUploads();
  
  useEffect(() => {
    fetchLibrary();
  }, []);

  useEffect(() => {
    fetchDevice();
  }, [])

  const fetchLibrary = async () => {
    try {
      const response = await axios.get('/library');
      setGames(response.data);
    } catch (error) {
      console.error("Failed to fetch library: ", error);
    }
  };

  const fetchDevice = async () => {
    try {
      const response = await axios.get('/device');
      setStorageDevice(response.data);
    } catch (error) {
      console.error("Failed to fetch device: ", error);
      setStorageDevice(null);
    }
  };

  const handleAddGameClick = () => {
    if (storageDevice) {
      setGameModalOpen(true);
    } else {
      setSettingsModalOpen(true);
      alert("Please configure a storage device first.")
    }
  };

  const handleDeleteGame = async (serial : string) => {
    try { 
      await axios.delete(`/library/${serial}`)
      fetchLibrary();
      setSelectedGame(null);
    } catch (error) {
      console.error("Failed to delete game: ", error);
      alert("Failed to delete game from library.");
    }
  };

  const handleGameModalClose = async () => {
    setGameModalOpen(false);
    fetchLibrary();
    clearCompleted();
  };

  const onUpdatePath = async (newPath: string) => {
    try {
      const response = await axios.post(`/set-device`, null, {
        params: { path: newPath }
      });

      if (response.data.status === "success") {
        fetchDevice();
        fetchLibrary();
        return true; // <--- Signal Success
      } else {
        alert(`Error!\nBe sure directory exists & device is formatted as exFAT`);
        return false; // <--- Signal Failure
      }
    } catch (error) {
      console.error(error);
      alert("Failed to reach server.");
      return false; // <--- Signal Failure
    }
  };

  const handleSearch = async (query : string) => {
    setGameQuery(query)
  }

  return (
    <>
      <Header setSettingsModalOpen={setSettingsModalOpen} OnQuery={handleSearch} />
      <main>
        <div onDragOver={(e) => {e.preventDefault(); if (storageDevice !== null) setGameModalOpen(true)}} onDrop={(e) => {if (storageDevice === null) { e.preventDefault(); alert("Please select a storage device first."); }}}>
          <SettingsModal isOpen={settingsModalOpen} onClose={() => {setSettingsModalOpen(false); fetchLibrary();}} device={storageDevice || undefined} onUpdatePath={onUpdatePath} onRefresh={fetchDevice}/>
          <AddGameModal isOpen={gameModalOpen} queue={queue} onUpload={uploadFiles} onClose={handleGameModalClose} onRemove={removeFile} />
          <GameViewModal isOpen={!!selectedGame} onClose={() => setSelectedGame(null)} game={selectedGame} onDelete={handleDeleteGame} />
          <Grid games={games} onGameClick={(game) => setSelectedGame(game)} filter={gameQuery}/>
          <div className="fixed bottom-8 right-8 shadow-lg">
            <IconButton icon={<Plus size={48} className="text-zinc-100" />} bgColor="bg-sky-600" onClick={handleAddGameClick} />
          </div>
        </div>
      </main>
    </>
  )
}

export default App
