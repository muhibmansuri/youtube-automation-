// State Management
let currentProjectId = null;
let allScenes = [];
let currentFilter = 'ALL';
let eventSource = null;

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
    initSSE();
    loadProjects();
    loadSettings();
    pollStatus();
    setInterval(pollStatus, 5000);
});

// --- Tab Switching ---
function switchTab(tabId) {
    document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

    const btn = document.querySelector(`.nav-tab[data-tab='${tabId}']`);
    if (btn) btn.classList.add("active");

    const pane = document.getElementById(tabId);
    if (pane) pane.classList.add("active");

    if (tabId === "tab-storyboard") loadScenes();
    if (tabId === "tab-compiler") checkMovieStatus();
}

function updateDurationCalc(val) {
    document.getElementById("durationVal").innerText = val;
    const totalClips = Math.round((val * 60) / 8);
    document.getElementById("totalClipsVal").innerText = totalClips;
}

// --- SSE Real-time Updates ---
function initSSE() {
    if (eventSource) eventSource.close();
    eventSource = new EventSource("/api/events");

    eventSource.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            handleRealtimeEvent(msg);
        } catch (err) {
            // Heartbeats or raw string
        }
    };

    eventSource.onerror = () => {
        setTimeout(initSSE, 5000);
    };
}

function handleRealtimeEvent(event) {
    const type = event.type;
    const data = event.data || {};

    if (type === "log") {
        appendLog(data.level, data.message, data.timestamp);
    } else if (type === "browser_preview") {
        const img = document.getElementById("browserPreviewImg");
        if (img && data.image_url) {
            img.src = data.image_url;
        }
    } else if (type === "scene_updated") {
        updateSceneCardState(data);
        updateCounters();
    } else if (type === "pipeline_started") {
        setPipelineUIState("RUNNING");
    } else if (type === "pipeline_paused") {
        setPipelineUIState("PAUSED");
    } else if (type === "pipeline_resumed") {
        setPipelineUIState("RUNNING");
    } else if (type === "pipeline_stopped") {
        setPipelineUIState("IDLE");
    } else if (type === "compile_progress") {
        const box = document.getElementById("compileProgressBox");
        const bar = document.getElementById("compileProgressBar");
        const txt = document.getElementById("compileStatusText");
        if (box) box.style.display = "block";
        if (bar) bar.style.width = `${data.percent}%`;
        if (txt) txt.innerText = data.message || `Compiling: ${data.percent}%`;
    } else if (type === "compile_completed") {
        const box = document.getElementById("compileProgressBox");
        if (box) box.style.display = "none";
        checkMovieStatus();
        alert("🎉 Master Movie compilation completed!");
    } else if (type === "verification_required") {
        alert("🛑 Cloudflare challenge or login required on TAAFT! Click 'Open Interactive Browser' to complete verification.");
    } else if (type === "quota_limit_reached") {
        alert("⚠️ Daily generation quota (100 videos) exhausted! Pipeline paused until reset.");
    }
}

// --- Projects ---
async function loadProjects() {
    try {
        const res = await fetch("/api/projects");
        const data = await res.json();
        const select = document.getElementById("projectSelect");
        select.innerHTML = '<option value="">-- Select or Create Project --</option>';

        if (data.projects && data.projects.length > 0) {
            data.projects.forEach(p => {
                const opt = document.createElement("option");
                opt.value = p.id;
                opt.innerText = `${p.name} (${p.genre})`;
                select.appendChild(opt);
            });

            // Set first project as active if none selected
            if (!currentProjectId) {
                switchProject(data.projects[0].id);
            }
        }
    } catch (e) {
        console.error("Error loading projects:", e);
    }
}

async function switchProject(projectId) {
    if (!projectId) return;
    currentProjectId = projectId;
    document.getElementById("projectSelect").value = projectId;

    try {
        const res = await fetch(`/api/projects/${projectId}`);
        const data = await res.json();
        if (data.success && data.project) {
            populateProjectDetails(data.project);
            updateCounters(data.stats);
            loadScenes();
            checkMovieStatus();
        }
    } catch (e) {
        console.error("Error switching project:", e);
    }
}

function populateProjectDetails(p) {
    document.getElementById("setupTitle").value = p.name || "";
    document.getElementById("setupGenre").value = p.genre || "Cinematic Sci-Fi / Cyberpunk";
    document.getElementById("setupDuration").value = p.target_duration_mins || 120;
    updateDurationCalc(p.target_duration_mins || 120);
    document.getElementById("setupStoryline").value = p.storyline || "";
    document.getElementById("setupCharacter").value = p.character_profile || "";

    if (document.getElementById("setupModelType")) {
        document.getElementById("setupModelType").value = p.model_type || "Fast";
    }
    if (document.getElementById("taaftModelSelect")) {
        document.getElementById("taaftModelSelect").value = p.model_type || "Fast";
    }

    // Gallery
    renderRefGallery(p.master_ref_images || []);
}

function renderRefGallery(images) {
    const gal = document.getElementById("refGallery");
    gal.innerHTML = "";
    if (!images || images.length === 0) {
        gal.innerHTML = '<div class="empty-state">No master reference images uploaded yet.</div>';
        return;
    }

    images.forEach(img => {
        const filename = img.split(/[\/\\]/).pop();
        const url = `/projects/${currentProjectId}/master_refs/${filename}`;
        const el = document.createElement("img");
        el.className = "ref-thumb";
        el.src = url;
        el.title = filename;
        gal.appendChild(el);
    });
}

async function saveProjectSetup() {
    if (!currentProjectId) {
        alert("Please create or select a project first.");
        return;
    }

    const payload = {
        name: document.getElementById("setupTitle").value.trim(),
        genre: document.getElementById("setupGenre").value,
        target_duration_mins: parseInt(document.getElementById("setupDuration").value),
        storyline: document.getElementById("setupStoryline").value.trim(),
        character_profile: document.getElementById("setupCharacter").value.trim(),
        model_type: document.getElementById("setupModelType") ? document.getElementById("setupModelType").value : "Fast"
    };

    try {
        const res = await fetch(`/api/projects/${currentProjectId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        alert("Movie Setup saved successfully!");
        loadProjects();
    } catch (e) {
        alert("Error saving setup: " + e.message);
    }
}

// Upload Master Ref
async function handleRefUpload(files) {
    if (!currentProjectId) {
        alert("Please select a project first.");
        return;
    }
    if (!files || files.length === 0) return;

    const fd = new FormData();
    fd.append("type", "master_ref");
    for (let f of files) fd.append("files", f);

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/upload_ref`, {
            method: "POST",
            body: fd
        });
        const data = await res.json();
        if (data.success) {
            renderRefGallery(data.master_ref_images);
            alert("Master Reference Image(s) attached!");
        }
    } catch (e) {
        alert("Upload failed: " + e.message);
    }
}

// Upload Audio
async function handleAudioUpload(files) {
    if (!currentProjectId) return;
    if (!files || files.length === 0) return;

    const fd = new FormData();
    fd.append("type", "audio");
    for (let f of files) fd.append("files", f);

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/upload_ref`, {
            method: "POST",
            body: fd
        });
        const data = await res.json();
        if (data.success) {
            alert("Soundtrack file uploaded successfully!");
        }
    } catch (e) {
        alert("Audio upload failed: " + e.message);
    }
}

// --- Storyboard & Scenes ---
async function loadScenes() {
    if (!currentProjectId) return;
    try {
        const res = await fetch(`/api/projects/${currentProjectId}/scenes`);
        const data = await res.json();
        if (data.success) {
            allScenes = data.scenes || [];
            updateCounters(data.stats);
            renderScenes(currentFilter);
        }
    } catch (e) {
        console.error("Error loading scenes:", e);
    }
}

function filterScenes(status) {
    currentFilter = status;
    document.querySelectorAll(".filter-chip").forEach(c => c.classList.remove("active"));
    const btn = event ? event.target : null;
    if (btn) btn.classList.add("active");
    renderScenes(status);
}

function renderScenes(filter) {
    const grid = document.getElementById("storyboardGrid");
    grid.innerHTML = "";

    const filtered = filter === "ALL" ? allScenes : allScenes.filter(s => s.status === filter);

    if (filtered.length === 0) {
        grid.innerHTML = `
        <div class="empty-state large">
            <i data-lucide="clapperboard" class="large-icon"></i>
            <h4>No ${filter !== "ALL" ? filter : ""} scenes found</h4>
            <p>Click "Generate Scenes with Gemini" above to automatically generate 8-second cinematic prompts.</p>
        </div>`;
        lucide.createIcons();
        return;
    }

    filtered.forEach(s => {
        const card = document.createElement("div");
        card.className = `scene-card status-${s.status.toLowerCase()}`;
        card.id = `sceneCard_${s.scene_number}`;

        const lastFrameSrc = s.last_frame_url || "";
        const clipSrc = s.clip_url || "";

        card.innerHTML = `
            <div class="scene-card-header">
                <span class="scene-badge-id">SCENE #${String(s.scene_number).padStart(3, '0')}</span>
                <span class="badge badge-${s.status === 'COMPLETED' ? 'success' : (s.status === 'GENERATING' ? 'pulse' : (s.status === 'FAILED' ? 'danger' : 'warning'))}">
                    ${s.status}
                </span>
            </div>
            <div class="scene-media-row">
                ${lastFrameSrc ? `<img src="${lastFrameSrc}" class="scene-thumb" title="Extracted Final Frame" alt="Final Frame">` : `<div class="scene-thumb-placeholder">Last Frame (Pending)</div>`}
                ${clipSrc ? `
                    <div class="scene-thumb-placeholder" style="cursor: pointer; background: rgba(99,102,241,0.1);" onclick="previewVideo('${clipSrc}', 'Scene #${s.scene_number}')">
                        <i data-lucide="play-circle" style="width: 28px; height: 28px; color: var(--primary);"></i>
                        <span style="display:block; margin-top: 4px; font-weight: 600;">Play Clip</span>
                    </div>
                ` : `<div class="scene-thumb-placeholder">Video Clip (Pending)</div>`}
            </div>
            <div class="scene-card-body">
                <div class="scene-title-text">${s.title || `Scene ${s.scene_number}`}</div>
                <div class="scene-prompt-box">${escapeHtml(s.prompt)}</div>
                ${s.dialogue ? `
                    <div class="scene-dialogue-badge" style="margin-top: 8px; padding: 6px 10px; background: rgba(99,102,241,0.12); border-left: 3px solid #6366f1; border-radius: 4px; font-size: 0.74rem;">
                        <span style="color: #818cf8; font-weight: 600;"><i data-lucide="mic" style="width: 12px; height: 12px; display: inline;"></i> ${escapeHtml(s.dialogue.voice_name || s.dialogue.character)}:</span>
                        <div style="color: #f1f5f9; margin-top: 2px; font-style: italic;">"${escapeHtml(s.dialogue.text)}"</div>
                    </div>
                ` : `
                    <div style="margin-top: 6px; font-size: 0.70rem; color: #64748b;">
                        <i data-lucide="volume-x" style="width: 11px; height: 11px; display: inline;"></i> Ambient Visual Scene (Clean Audio)
                    </div>
                `}
            </div>
            <div class="scene-card-footer">
                <span style="font-size: 0.72rem; color: var(--text-muted);">Dur: 8.0s</span>
                <button class="btn btn-xs btn-outline" onclick="regenerateScene(${s.scene_number})">
                    <i data-lucide="refresh-cw"></i> Regenerate
                </button>
            </div>
        `;
        grid.appendChild(card);
    });
    lucide.createIcons();
}

function updateSceneCardState(data) {
    const card = document.getElementById(`sceneCard_${data.scene_number}`);
    if (card) {
        card.className = `scene-card status-${data.status.toLowerCase()}`;
        const badge = card.querySelector(".scene-card-header .badge");
        if (badge) {
            badge.innerText = data.status;
            badge.className = `badge badge-${data.status === 'COMPLETED' ? 'success' : (data.status === 'GENERATING' ? 'pulse' : (data.status === 'FAILED' ? 'danger' : 'warning'))}`;
        }
    }
}

function updateCounters(stats) {
    if (!stats) return;
    document.getElementById("statTotalScenes").innerText = stats.total || 0;
    document.getElementById("statCompletedScenes").innerText = stats.completed || 0;
    document.getElementById("statPendingScenes").innerText = stats.pending || 0;
    document.getElementById("statFailedScenes").innerText = stats.failed || 0;
    document.getElementById("statProgressPct").innerText = `${stats.progress_percent || 0}%`;
}

// Script Generation Modal
function openScriptGenModal() {
    if (!currentProjectId) {
        alert("Please select or create a project first.");
        return;
    }
    document.getElementById("scriptGenModal").classList.add("active");
}
function closeScriptGenModal() {
    document.getElementById("scriptGenModal").classList.remove("active");
}

async function submitScriptGeneration() {
    const btn = document.getElementById("btnSubmitScriptGen");
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="pulse-dot"></i> Generating Prompts...';

    const start = parseInt(document.getElementById("scriptGenStart").value) || 1;
    const batch = parseInt(document.getElementById("scriptGenBatch").value) || 30;
    const mode = document.getElementById("scriptGenMode") ? document.getElementById("scriptGenMode").value : "autonomous";

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/generate_script`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start_scene: start, batch_size: batch, mode: mode })
        });
        const data = await res.json();
        if (data.success) {
            closeScriptGenModal();
            loadScenes();
            alert(`🎉 Successfully generated ${data.scenes_generated} scenes with strict continuity prompts!`);
        } else {
            alert("Generation error: " + data.error);
        }
    } catch (e) {
        alert("Error: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="sparkles"></i> Generate Prompts';
        lucide.createIcons();
    }
}

async function regenerateScene(sceneNum) {
    const instruction = prompt(`Enter custom director guidance for Scene #${sceneNum}:`, "Make lighting dramatic with high contrast");
    if (instruction === null) return;

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/scenes/${sceneNum}/regenerate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ instruction })
        });
        const data = await res.json();
        if (data.success) {
            loadScenes();
            alert(`Scene #${sceneNum} regenerated!`);
        } else {
            alert("Error: " + data.error);
        }
    } catch (e) {
        alert("Failed: " + e.message);
    }
}

// --- Automation Control ---
async function updateProjectModel(model) {
    if (!currentProjectId) return;
    try {
        await fetch(`/api/projects/${currentProjectId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model_type: model })
        });
        if (document.getElementById("setupModelType")) {
            document.getElementById("setupModelType").value = model;
        }
        if (document.getElementById("taaftModelSelect")) {
            document.getElementById("taaftModelSelect").value = model;
        }
        appendLog("INFO", `Switched TAAFT generation mode to: ${model}`, new Date().toLocaleTimeString());
    } catch (e) {
        console.error("Failed to update model:", e);
    }
}

async function startAutomation() {
    if (!currentProjectId) {
        alert("Please select a project first.");
        return;
    }
    const headless = document.getElementById("headlessToggle").checked;
    const model = document.getElementById("taaftModelSelect") ? document.getElementById("taaftModelSelect").value : "Fast";
    try {
        const res = await fetch("/api/pipeline/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: currentProjectId, headless, model_type: model })
        });
        const data = await res.json();
        if (data.success) {
            setPipelineUIState("RUNNING");
        } else {
            alert(data.message || data.error);
        }
    } catch (e) {
        alert("Failed to start: " + e.message);
    }
}

async function pauseAutomation() {
    try {
        await fetch("/api/pipeline/pause", { method: "POST" });
        setPipelineUIState("PAUSED");
    } catch (e) {
        alert("Failed to pause: " + e.message);
    }
}

async function resumeAutomation() {
    try {
        await fetch("/api/pipeline/resume", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: currentProjectId })
        });
        setPipelineUIState("RUNNING");
    } catch (e) {
        alert("Failed to resume: " + e.message);
    }
}

async function stopAutomation() {
    try {
        await fetch("/api/pipeline/stop", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: currentProjectId })
        });
        setPipelineUIState("IDLE");
    } catch (e) {
        alert("Failed to stop: " + e.message);
    }
}

async function launchLoginBrowser() {
    try {
        appendLog("INFO", "🌐 Spawning interactive browser window for manual login...", new Date().toLocaleTimeString());
        const res = await fetch("/api/pipeline/launch_browser", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            alert("🌐 Browser window launched!\n\n1. Check your taskbar / screen for the opened Chrome/Chromium window.\n2. Complete the Cloudflare verification and log in to TAAFT.\n3. Once logged in, close that browser window.\n\nTip: You can also double-click 'login.bat' in the project folder anytime.");
        } else {
            alert("Could not launch browser automatically: " + (data.error || "Please run login.bat directly"));
        }
    } catch (e) {
        alert("Failed to launch browser: " + e.message + "\n\nPlease double-click 'login.bat' in your project folder to open the browser directly.");
    }
}

function setPipelineUIState(state) {
    const pill = document.getElementById("pipelineStatusPill");
    const txt = document.getElementById("pipelineStatusText");
    const btnStart = document.getElementById("btnStartPipeline");
    const btnPause = document.getElementById("btnPausePipeline");
    const btnResume = document.getElementById("btnResumePipeline");
    const btnStop = document.getElementById("btnStopPipeline");

    pill.className = `status-pill ${state.toLowerCase()}`;
    txt.innerText = `Pipeline: ${state}`;

    if (state === "RUNNING") {
        btnStart.disabled = true;
        btnPause.disabled = false;
        btnPause.style.display = "inline-flex";
        btnResume.style.display = "none";
        btnStop.disabled = false;
    } else if (state === "PAUSED") {
        btnStart.disabled = true;
        btnPause.style.display = "none";
        btnResume.style.display = "inline-flex";
        btnStop.disabled = false;
    } else {
        btnStart.disabled = false;
        btnPause.disabled = true;
        btnPause.style.display = "inline-flex";
        btnResume.style.display = "none";
        btnStop.disabled = true;
    }
}

async function pollStatus() {
    if (!currentProjectId) return;
    try {
        const res = await fetch(`/api/pipeline/status?project_id=${currentProjectId}`);
        const data = await res.json();
        if (data.success && data.status) {
            setPipelineUIState(data.status.status);
            document.getElementById("quotaCounterText").innerText = `Quota: ${data.status.quota_left} / ${data.status.quota_total}`;
            if (data.status.status_message) {
                document.getElementById("currentActionStatus").innerText = `Status: ${data.status.status_message}`;
            }
            if (data.status.stats) {
                updateCounters(data.status.stats);
            }
        }
    } catch (e) {}
}

function appendLog(level, message, timestamp) {
    const terminal = document.getElementById("terminalLogs");
    if (!terminal) return;
    const line = document.createElement("div");
    line.className = `log-line ${level.toLowerCase()}`;
    line.innerText = `[${timestamp || ''}] [${level}] ${message}`;
    terminal.appendChild(line);
    terminal.scrollTop = terminal.scrollHeight;
}

function clearLogs() {
    const terminal = document.getElementById("terminalLogs");
    if (terminal) terminal.innerHTML = "";
}

// --- Movie Compiler Studio ---
async function handleStudioAudioUpload(e) {
    if (!currentProjectId) { alert("Please select a project first."); return; }
    const file = e.target.files[0];
    if (!file) return;
    const statusEl = document.getElementById("studioAudioStatus");
    if (statusEl) statusEl.innerText = "Uploading background music...";
    const fd = new FormData();
    fd.append("file", file);
    fd.append("type", "audio");
    try {
        const res = await fetch(`/api/projects/${currentProjectId}/upload_ref`, { method: "POST", body: fd });
        const data = await res.json();
        if (data.success && statusEl) {
            statusEl.innerText = `✅ Music Uploaded: ${file.name}`;
            statusEl.style.color = "#10b981";
        }
    } catch (err) {
        if (statusEl) statusEl.innerText = "❌ Upload failed: " + err.message;
    }
}

async function triggerMovieCompilation() {
    if (!currentProjectId) return;
    const transition = document.getElementById("compileTransition").value;
    const resolution = document.getElementById("compileResolution").value;
    const normalize = document.getElementById("compileNormalize").value === "true";
    const enhance = document.getElementById("compileEnhance") ? document.getElementById("compileEnhance").value === "true" : true;
    const volume = parseFloat(document.getElementById("compileMusicVol").value);
    const audioMode = document.getElementById("compileAudioMode") ? document.getElementById("compileAudioMode").value : "storyteller";
    const cinemaWidescreen = document.getElementById("compileWidescreen") ? document.getElementById("compileWidescreen").value === "true" : true;
    const colorGrade = document.getElementById("compileColorGrade") ? document.getElementById("compileColorGrade").value : "noir";
    const burnSubtitles = document.getElementById("compileSubtitles") ? document.getElementById("compileSubtitles").value === "true" : true;

    const box = document.getElementById("compileProgressBox");
    if (box) box.style.display = "block";
    const statusText = document.getElementById("compileStatusText");
    if (statusText) statusText.innerText = "Starting Cinema Editing & Compilation...";

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/compile`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                transition_mode: transition,
                resolution,
                normalize_audio: normalize,
                enhance_quality: enhance,
                music_volume: volume,
                audio_mode: audioMode,
                cinema_widescreen: cinemaWidescreen,
                color_grade: colorGrade,
                burn_subtitles: burnSubtitles
            })
        });
        const data = await res.json();
        if (data.success) {
            appendLog("INFO", data.message, new Date().toLocaleTimeString());
        } else {
            alert(data.error);
            if (box) box.style.display = "none";
        }
    } catch (e) {
        alert("Compilation error: " + e.message);
        if (box) box.style.display = "none";
    }
}

function playCompiledMovieVersion(url, filename, sizeMb) {
    const player = document.getElementById("finalMovieVideo");
    const src = document.getElementById("finalMovieSource");
    const dlBtn = document.getElementById("downloadMovieBtn");
    const badge = document.getElementById("movieBadge");
    if (src && player) {
        src.src = url;
        player.load();
        player.play().catch(() => {});
    }
    if (dlBtn) {
        dlBtn.href = url;
        dlBtn.setAttribute("download", filename);
    }
    if (badge) {
        badge.innerText = `${filename} (${sizeMb} MB)`;
        badge.className = "badge badge-success";
    }
}

async function triggerAIUpscaling() {
    if (!currentProjectId) {
        alert("Please select a project first.");
        return;
    }
    const box = document.getElementById("compileProgressBox");
    if (box) box.style.display = "block";
    const statusText = document.getElementById("compileStatusText");
    if (statusText) statusText.innerText = "Initializing Real-ESRGAN GPU 4K Upscaler...";

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/ai_upscale`, {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });
        const data = await res.json();
        if (data.success) {
            appendLog("INFO", data.message, new Date().toLocaleTimeString());
        } else {
            alert(data.error);
            if (box) box.style.display = "none";
        }
    } catch (e) {
        alert("AI Upscaling error: " + e.message);
        if (box) box.style.display = "none";
    }
}

async function checkMovieStatus() {
    if (!currentProjectId) return;
    try {
        const res = await fetch(`/api/projects/${currentProjectId}/movie_status`);
        const data = await res.json();
        const player = document.getElementById("finalMovieVideo");
        const src = document.getElementById("finalMovieSource");
        const dlRow = document.getElementById("movieDownloadRow");
        const dlBtn = document.getElementById("downloadMovieBtn");
        const badge = document.getElementById("movieBadge");

        const versionsEl = document.getElementById("compiledVersionsList");
        if (data.has_movie) {
            src.src = data.url;
            player.load();
            dlBtn.href = data.url;
            dlBtn.setAttribute("download", data.filename);
            dlRow.style.display = "block";
            badge.innerText = `${data.filename} (${data.file_size_mb} MB)`;
            badge.className = "badge badge-success";

            if (versionsEl && data.all_movies && data.all_movies.length > 0) {
                versionsEl.innerHTML = `<div style="font-size:12px; color:var(--text-muted); margin-bottom:8px;">📂 બનેલી બધી ફાઇલ્સ (ક્લિક કરીને પ્લે કરો):</div>` +
                    data.all_movies.map(m => `
                        <button class="btn btn-outline" style="margin:4px 6px 4px 0; font-size:12px; padding:6px 10px;"
                            onclick="playCompiledMovieVersion('${m.url}', '${m.filename}', '${m.file_size_mb}')">
                            🎬 ${m.filename} (${m.file_size_mb} MB)
                        </button>
                    `).join("");
            }
        } else {
            dlRow.style.display = "none";
            if (versionsEl) versionsEl.innerHTML = "";
            badge.innerText = "No Movie Compiled Yet";
            badge.className = "badge badge-purple";
        }
    } catch (e) {}
}

// --- Video Preview Modal ---
function previewVideo(url, title) {
    document.getElementById("videoPreviewTitle").innerText = title || "Clip Preview";
    const player = document.getElementById("modalVideoPlayer");
    const src = document.getElementById("modalVideoSource");
    src.src = url;
    player.load();
    document.getElementById("videoPreviewModal").classList.add("active");
}

function closeVideoPreviewModal() {
    const player = document.getElementById("modalVideoPlayer");
    player.pause();
    document.getElementById("videoPreviewModal").classList.remove("active");
}

// --- Project Modal ---
function openNewProjectModal() {
    document.getElementById("newProjectModal").classList.add("active");
}
function closeNewProjectModal() {
    document.getElementById("newProjectModal").classList.remove("active");
}

async function submitCreateProject() {
    const name = document.getElementById("modalProjectName").value.trim();
    const genre = document.getElementById("modalGenre").value;
    const duration = parseInt(document.getElementById("modalDuration").value) || 120;
    const storyline = document.getElementById("modalStoryline").value.trim();

    if (!storyline) {
        alert("Please provide a story outline or premise.");
        return;
    }

    try {
        const res = await fetch("/api/projects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, genre, target_duration_mins: duration, storyline })
        });
        const data = await res.json();
        if (data.success) {
            closeNewProjectModal();
            await loadProjects();
            switchProject(data.project.id);
            alert(`Project "${data.project.name}" created!`);
        }
    } catch (e) {
        alert("Error creating project: " + e.message);
    }
}

// --- Settings ---
async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const data = await res.json();
        if (data.success) {
            if (data.gemini_api_key_masked) {
                document.getElementById("settingsGeminiKey").placeholder = `Configured: ${data.gemini_api_key_masked}`;
            }
            if (data.settings && data.settings.gemini_model) {
                document.getElementById("settingsGeminiModel").value = data.settings.gemini_model;
            }
            document.getElementById("diagFfmpeg").innerText = `Active (${data.ffmpeg_path.split(/[\/\\]/).pop()})`;
            document.getElementById("diagFfmpeg").className = "badge badge-success";
        }
    } catch (e) {}
}

async function saveSettings() {
    const key = document.getElementById("settingsGeminiKey").value.trim();
    const model = document.getElementById("settingsGeminiModel").value;

    const payload = { gemini_model: model };
    if (key) payload.gemini_api_key = key;

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        alert(data.message || "Settings updated!");
        loadSettings();
    } catch (e) {
        alert("Error saving settings: " + e.message);
    }
}

async function testGeminiConnection() {
    try {
        const res = await fetch("/api/settings/test_gemini", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            alert("✅ " + data.message);
        } else {
            alert("❌ Connection failed: " + data.error);
        }
    } catch (e) {
        alert("Test error: " + e.message);
    }
}

async function testFfmpegDiagnostic() {
    try {
        const res = await fetch("/api/settings/test_ffmpeg", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            alert(`✅ FFmpeg is fully operational!\n${data.version}\nPath: ${data.path}`);
        } else {
            alert("❌ FFmpeg test failed: " + data.error);
        }
    } catch (e) {
        alert("Error: " + e.message);
    }
}

function escapeHtml(text) {
    if (!text) return "";
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// --- Neural Voice Studio Functions ---
async function testVoicePreview() {
    const voiceSelect = document.getElementById("voiceSelector");
    const textInput = document.getElementById("voiceSampleText");
    const btn = document.getElementById("btnVoicePreview");
    const playerBox = document.getElementById("voiceAudioPlayerBox");
    const player = document.getElementById("voiceAudioPlayer");

    const voiceId = voiceSelect ? voiceSelect.value : "hi_arjun";
    const sampleText = (textInput && textInput.value.trim()) ? textInput.value.trim() : "हेलो, यह कोडऑरा सिनेमा स्टूडियो की आवाज़ है।";

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> Synthesizing...';
    if (window.lucide) lucide.createIcons();

    try {
        const res = await fetch("/api/voices/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ voice_id: voiceId, text: sampleText })
        });
        const data = await res.json();
        if (data.success && data.audio_url) {
            player.src = data.audio_url;
            playerBox.style.display = "flex";
            player.play();
        } else {
            alert("❌ Voice preview failed: " + (data.error || "Unknown error"));
        }
    } catch (e) {
        alert("Voice test network error: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="volume-2"></i> Test Voice';
        if (window.lucide) lucide.createIcons();
    }
}

async function triggerRedubProject() {
    if (!currentProjectId) {
        alert("Please select a project first.");
        return;
    }

    if (!confirm("Are you sure you want to re-dub all completed scenes with clean neural voice?\n\nThis will eliminate TAAFT's robotic noise and apply pure studio dialogue!")) {
        return;
    }

    try {
        const res = await fetch(`/api/projects/${currentProjectId}/redub`, { method: "POST" });
        if (!res.ok) {
            if (res.status === 404) {
                alert("⚠️ Server route not found (HTTP 404).\n\nPlease CLOSE your terminal window and RE-RUN run.bat so the server loads the latest code!");
                return;
            }
            const errText = await res.text();
            throw new Error(`HTTP ${res.status}: ${errText.substring(0, 120)}`);
        }
        const data = await res.json();
        if (data.success) {
            alert(`✅ ${data.message}`);
            switchTab("tab-automation");
        } else {
            alert("❌ Re-dub failed: " + (data.error || "Unknown error"));
        }
    } catch (e) {
        alert("Re-dub notice: " + e.message);
    }
}
