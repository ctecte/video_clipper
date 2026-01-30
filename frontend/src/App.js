import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import './App.css';

// Configure Backend URL
const API_BASE = 'http://localhost:5000';

function App() {
  const [activeTab, setActiveTab] = useState('upload'); // 'upload' or 'youtube'
  const [file, setFile] = useState(null);
  const [youtubeUrl, setYoutubeUrl] = useState('');
  
  // Job State
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null); // 'queued', 'processing', 'completed', 'failed'
  const [results, setResults] = useState([]);
  const [error, setError] = useState('');

  // Upload UX State
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  // --- 1. CLEANUP UTILITY ---
  // We define this first so it can be used by reset and the effect hook
  const cleanupSession = useCallback((id) => {
    if (!id) return;
    try {
      // Use fire-and-forget for speed
      axios.post(`${API_BASE}/cleanup/${id}`).catch(err => console.error(err)); 
    } catch (err) {
      console.error("Cleanup failed:", err);
    }
  }, []);

  // --- 2. RESET FUNCTION ---
  // Consolidated into one single declaration
  const reset = () => {
    // Trigger cleanup before clearing state
    if (jobId) cleanupSession(jobId);

    setJobId(null);
    setStatus(null);
    setResults([]);
    setFile(null);
    setYoutubeUrl('');
    setError('');
    setUploading(false);
    setUploadProgress(0);
  };

  // --- 3. POLLING LOGIC ---
  const checkStatus = useCallback(async () => {
    if (!jobId) return;

    try {
      const res = await axios.get(`${API_BASE}/status/${jobId}`);
      setStatus(res.data.status);
      
      // Update progress bar if backend sends percentage
      if (res.data.progress !== undefined) {
        setUploadProgress(res.data.progress);
      }

      if (res.data.status === 'completed') {
        setResults(res.data.results);
      } else if (res.data.status === 'failed') {
        setError(res.data.error || 'Processing failed unexpectedly.');
      }
    } catch (err) {
      console.error("Polling error:", err);
    }
  }, [jobId]);

  // Effect: Run Polling
  useEffect(() => {
    let interval;
    if (jobId && status !== 'completed' && status !== 'failed') {
      interval = setInterval(checkStatus, 2000);
    }
    return () => clearInterval(interval);
  }, [jobId, status, checkStatus]);

  // Effect: Handle Browser Tab Close
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (jobId) {
        // navigator.sendBeacon is reliable for page exits
        navigator.sendBeacon(`${API_BASE}/cleanup/${jobId}`);
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [jobId]);


  // --- 4. ACTION HANDLERS ---
  const handleUpload = async () => {
    if (!file) return alert("Please select a file!");
    if (!file.name.toLowerCase().endsWith('.mp4')) {
      return alert("Only .mp4 files are allowed!");
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
      setError('');
      setUploading(true);
      setStatus('uploading');
      setUploadProgress(0);

      const res = await axios.post(`${API_BASE}/upload`, formData, {
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          setUploadProgress(percentCompleted);
        }
      });

      setJobId(res.data.job_id);
      setStatus('queued');
      setUploading(false);
    } catch (err) {
      console.error(err);
      setStatus(null);
      setError(err.response?.data?.error || "Upload failed. Is backend running?");
      setUploading(false);
    }
  };

  const handleYoutube = async () => {
    if (!youtubeUrl) return alert("Enter a URL!");
    
    try {
      setError('');
      setUploading(true);
      setStatus('initializing');
      
      const res = await axios.post(`${API_BASE}/youtube`, { url: youtubeUrl });
      setJobId(res.data.job_id);
      setUploading(false);
    } catch (err) {
      console.error(err);
      setStatus(null);
      setError(err.response?.data?.error || "YouTube download failed.");
      setUploading(false);
    }
  };

  return (
    <div className="App">
      <header className="header">
        <h1>✂️ Videotto Clipper</h1>
        <p>AI-Powered Laughter Detection</p>
      </header>

      <div className="container">
        
        {/* INPUT SECTION */}
        {!jobId && (
          <div className="card input-section">
            <div className="tabs">
              <button 
                className={activeTab === 'upload' ? 'active' : ''} 
                onClick={() => setActiveTab('upload')}
                disabled={uploading}
              >
                📁 Upload MP4
              </button>
              <button 
                className={activeTab === 'youtube' ? 'active' : ''} 
                onClick={() => setActiveTab('youtube')}
                disabled={uploading}
              >
                📺 YouTube Link
              </button>
            </div>

            <div className="tab-content">
              {activeTab === 'upload' ? (
                <div className="upload-box">
                  <div className="file-input-wrapper">
                    <input 
                      type="file" 
                      accept=".mp4"
                      onChange={(e) => setFile(e.target.files[0])} 
                      disabled={uploading}
                    />
                  </div>
                  <button 
                    className="primary-btn" 
                    onClick={handleUpload} 
                    disabled={!file || uploading}
                  >
                    {uploading && status === 'uploading' 
                      ? `Uploading... ${uploadProgress}%` 
                      : "Start Processing"}
                  </button>
                </div>
              ) : (
                <div className="youtube-box">
                  <input 
                    type="text" 
                    placeholder="Paste YouTube URL here..." 
                    value={youtubeUrl}
                    onChange={(e) => setYoutubeUrl(e.target.value)}
                    disabled={uploading}
                  />
                  <button 
                    className="primary-btn" 
                    onClick={handleYoutube} 
                    disabled={!youtubeUrl || uploading}
                  >
                    {uploading ? "Starting..." : "Download & Process"}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ERROR MESSAGE */}
        {error && (
          <div className="error-banner">
            <span>❌ {error}</span>
            <button className="retry-btn" onClick={reset}>Try Again</button>
          </div>
        )}

        {/* STATUS LOADER */}
        {jobId && status !== 'completed' && !error && (
          <div className="card status-card">
            <div className="loader"></div>
            <h2>Processing Video...</h2>
            <div className="status-badge">{status ? status.toUpperCase() : 'LOADING...'}</div>
            
            <div className="progress-container">
                {(status === 'uploading' || status === 'processing' || status === 'downloading') && (
                    <div className="progress-bar-bg">
                        <div 
                            className="progress-bar-fill" 
                            style={{width: `${uploadProgress}%`}}
                        ></div>
                    </div>
                )}
            </div>
            
            <p className="subtext">
              {status === 'uploading' && `Uploading file... ${uploadProgress}%`}
              {status === 'processing' && `AI analyzing laughter... ${uploadProgress}%`}
              {status === 'downloading' && `Downloading from YouTube... ${uploadProgress}%`}
              {status === 'queued' && "Waiting for processor..."}
              {status === 'initializing' && "Initializing job..."}
            </p>
          </div>
        )}

        {/* RESULTS */}
        {status === 'completed' && (
          <div className="results-section">
            <div className="results-header">
              <h2>🎉 Top 3 Funny Moments</h2>
              <button className="secondary-btn" onClick={reset}>Process Another</button>
            </div>
            
            <div className="clips-grid">
              {results.map((clip) => (
                <div key={clip.id} className="clip-card">
                  <div className="video-wrapper">
                    <video controls preload="metadata">
                      <source src={`${API_BASE}${clip.url}`} type="video/mp4" />
                      Your browser does not support the video tag.
                    </video>
                  </div>
                  <div className="clip-info">
                    <h3>Clip #{clip.id}</h3>
                    <p className="filename" title={clip.filename}>{clip.filename}</p>
                    <a href={`${API_BASE}${clip.url}`} download>
                      <button className="download-btn">
                        <span>⬇</span> Download Clip
                      </button>
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}

export default App;
