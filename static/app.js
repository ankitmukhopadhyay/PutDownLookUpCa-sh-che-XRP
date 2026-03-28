// PUT UP — Frontend JavaScript

// ── GPS Helpers ──────────────────────────────────────────────────

function getLocation() {
    return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            reject(new Error('Geolocation is not supported by this browser'));
            return;
        }
        navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 10000,
        });
    });
}

async function useMyLocation() {
    const btn = document.getElementById('use-location-btn');
    btn.textContent = 'Getting location...';
    btn.disabled = true;
    try {
        const pos = await getLocation();
        document.getElementById('lat-input').value = pos.coords.latitude.toFixed(6);
        document.getElementById('lon-input').value = pos.coords.longitude.toFixed(6);
        const acc = Math.round(pos.coords.accuracy * 3.28084); // meters → feet
        document.getElementById('coord-display').textContent =
            `${pos.coords.latitude.toFixed(5)}, ${pos.coords.longitude.toFixed(5)}  (±${acc}ft accuracy)`;
        btn.textContent = '✓ Location Set';
    } catch (e) {
        btn.textContent = '📍 Use My Current Location';
        btn.disabled = false;
        alert('Could not get location: ' + e.message + '\nMake sure location permission is enabled.');
    }
}

// ── Registration ─────────────────────────────────────────────────

async function registerUser() {
    const name = document.getElementById('name-input').value.trim();
    if (!name) { alert('Enter your name.'); return; }

    const btn = document.getElementById('register-btn');
    const resultDiv = document.getElementById('register-result');
    btn.disabled = true;
    btn.textContent = 'Creating wallet...';
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = '<span class="spinner"></span> Requesting testnet funds (~15 seconds)...';

    try {
        const resp = await fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        const data = await resp.json();
        if (data.error) {
            resultDiv.innerHTML = `<span style="color:var(--negative)">Error: ${data.error}</span>`;
            btn.disabled = false;
            btn.textContent = 'Create My Wallet';
        } else {
            resultDiv.innerHTML =
                `<span style="color:var(--positive);font-weight:700">Wallet created!</span>\n` +
                `Name: ${data.name}\n` +
                `Address: ${data.address}\n` +
                `XRP Balance: ${data.xrp} XRP\n\n` +
                `<a href="${data.profile_url}" class="btn btn-gold" style="display:inline-block;margin-top:8px">View My Profile →</a>`;
        }
    } catch (e) {
        resultDiv.innerHTML = `<span style="color:var(--negative)">Network error: ${e.message}</span>`;
        btn.disabled = false;
        btn.textContent = 'Create My Wallet';
    }
}

// ── Event Creation ────────────────────────────────────────────────

async function createEvent() {
    const name = document.getElementById('event-name').value.trim();
    const datetimeVal = document.getElementById('event-time').value;
    const depositXrp = parseFloat(document.getElementById('deposit-xrp').value);
    const lat = document.getElementById('lat-input').value;
    const lon = document.getElementById('lon-input').value;

    const participantNames = Array.from(document.querySelectorAll('.participant-name'))
        .map(i => i.value.trim()).filter(Boolean);

    if (!name) { alert('Enter an event name.'); return; }
    if (!datetimeVal) { alert('Set a scheduled start time.'); return; }
    if (participantNames.length < 2) { alert('Enter names for all participants.'); return; }
    if (new Set(participantNames.map(n => n.toLowerCase())).size !== participantNames.length) {
        alert('All participant names must be unique.'); return;
    }
    if (isNaN(depositXrp) || depositXrp < 0) { alert('Enter a valid cost (0 or more).'); return; }
    if (!lat || !lon) { alert('Set the venue location first.'); return; }

    const scheduledTime = new Date(datetimeVal).getTime() / 1000;
    const n = participantNames.length;

    const btn = document.getElementById('create-btn');
    const resultDiv = document.getElementById('create-result');
    btn.textContent = 'Creating wallets...';
    btn.disabled = true;
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = `<span class="spinner"></span> Creating ${n} XRPL wallets (~${n * 15}s)...`;

    try {
        const resp = await fetch('/api/event/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                lat: parseFloat(lat),
                lon: parseFloat(lon),
                scheduled_time: scheduledTime,
                deposit_xrp: depositXrp,
                participant_names: participantNames,
            }),
        });
        const data = await resp.json();
        if (data.error) {
            resultDiv.innerHTML = `<span style="color:var(--negative)">Error: ${data.error}</span>`;
            btn.disabled = false;
            btn.textContent = 'Create Event & Wallets';
        } else {
            window.location.href = '/event';
        }
    } catch (e) {
        resultDiv.innerHTML = `<span style="color:var(--negative)">Network error: ${e.message}</span>`;
        btn.disabled = false;
        btn.textContent = 'Create Event & Wallets';
    }
}

// ── GPS Check-In ──────────────────────────────────────────────────

async function doCheckin(address) {
    const resultDiv = document.getElementById('checkin-result');
    const btn = document.getElementById('checkin-btn');

    resultDiv.classList.remove('hidden');
    resultDiv.textContent = 'Getting your location...';
    btn.disabled = true;

    try {
        const pos = await getLocation();
        resultDiv.textContent = 'Validating with server...';

        const resp = await fetch('/api/checkin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                address,
                lat: pos.coords.latitude,
                lon: pos.coords.longitude,
            }),
        });
        const data = await resp.json();

        if (data.error) {
            resultDiv.innerHTML = `<span style="color:var(--negative)">Error: ${data.error}</span>`;
            btn.disabled = false;
        } else if (data.valid) {
            resultDiv.innerHTML = `<span style="color:var(--positive);font-weight:700">Checked in! ${data.distance_ft}ft from venue (${data.elapsed_min} min into window)</span>`;
            btn.textContent = '✓ Checked In';
            setTimeout(() => { window.location.href = '/event'; }, 2000);
        } else {
            resultDiv.innerHTML = `<span style="color:var(--negative)">${data.reason}</span>`;
            btn.disabled = false;
        }
    } catch (e) {
        resultDiv.innerHTML = `<span style="color:var(--negative)">Location error: ${e.message}. Enable location permission and try again.</span>`;
        btn.disabled = false;
    }
}

// ── Event Resolve ─────────────────────────────────────────────────

async function resolveEvent() {
    const resultDiv = document.getElementById('resolve-result');
    const btn = document.getElementById('resolve-btn');

    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = '<span class="spinner"></span> Resolving on XRPL Testnet... (15–30 seconds)';
    btn.disabled = true;

    try {
        const resp = await fetch('/api/event/resolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await resp.json();

        if (data.error) {
            resultDiv.innerHTML = `<span style="color:var(--negative)">Error: ${data.error}</span>`;
            btn.disabled = false;
        } else {
            let html = `<span style="color:var(--positive);font-weight:700">Resolved: ${data.outcome.toUpperCase().replace(/_/g,' ')}</span>\n\n`;

            if (data.showups && data.showups.length) {
                html += `Showed up (${data.showups.length}): ${data.showups.join(', ')}\n`;
                if (data.deposit_xrp > 0)
                    html += `  Payout: ${data.payout_per_showup} XRP each\n`;
            }
            if (data.ghosts && data.ghosts.length) {
                html += `Ghosted (${data.ghosts.length}): ${data.ghosts.join(', ')}\n`;
            }

            html += '\nNew Karma Scores:\n';
            if (data.new_scores) {
                for (const [name, score] of Object.entries(data.new_scores)) {
                    html += `  ${name}: ${Math.floor(score)} KRM\n`;
                }
            }

            if (data.tx_hashes) {
                html += '\nTransaction Hashes:\n';
                const all = [
                    ...(data.tx_hashes.deposits||[]),
                    ...(data.tx_hashes.payments||[]),
                    ...(data.tx_hashes.karma||[]),
                ];
                for (const hash of all) {
                    if (hash) html += `  <a href="https://testnet.xrpl.org/transactions/${hash}" target="_blank" class="tx-link">${hash.substring(0, 20)}...</a>\n`;
                }
            }
            resultDiv.innerHTML = html;
            setTimeout(() => { window.location.href = '/leaderboard'; }, 4000);
        }
    } catch (e) {
        resultDiv.innerHTML = `<span style="color:var(--negative)">Network error: ${e.message}</span>`;
        btn.disabled = false;
    }
}

// ── Countdown Timers ──────────────────────────────────────────────

function startCountdown(endEpochMs, elementId, onExpire) {
    function update() {
        const el = document.getElementById(elementId);
        if (!el) return;
        const remaining = endEpochMs - Date.now();
        if (remaining <= 0) {
            el.textContent = '';
            if (onExpire) onExpire();
            return;
        }
        const mins = Math.floor(remaining / 60000);
        const secs = Math.floor((remaining % 60000) / 1000);
        el.textContent = `${mins}m ${secs}s remaining`;
        setTimeout(update, 1000);
    }
    update();
}

function startOpenCountdown(openEpochMs, elementId, onOpen) {
    function update() {
        const el = document.getElementById(elementId);
        if (!el) return;
        const until = openEpochMs - Date.now();
        if (until <= 0) {
            el.textContent = '';
            if (onOpen) onOpen();
            return;
        }
        const mins = Math.floor(until / 60000);
        const secs = Math.floor((until % 60000) / 1000);
        el.textContent = `Opens in ${mins}m ${secs}s`;
        setTimeout(update, 1000);
    }
    update();
}

// ── Misc ──────────────────────────────────────────────────────────

function copyAddress(address) {
    navigator.clipboard.writeText(address).then(function() {
        // Brief visual feedback
        const el = document.querySelector('.profile-address');
        if (el) {
            const orig = el.textContent;
            el.textContent = 'Copied!';
            setTimeout(() => { el.textContent = orig; }, 1500);
        }
    });
}

async function simulate(scenario, eventName) {
    const resultDiv = document.getElementById('sim-result');
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = '<span class="spinner"></span> Running on XRPL Testnet... (this takes ~15-30 seconds)';

    // Disable all buttons during simulation
    const buttons = document.querySelectorAll('.sim-buttons .btn');
    buttons.forEach(b => b.disabled = true);

    try {
        const response = await fetch('/api/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scenario: scenario, event_name: eventName }),
        });

        const data = await response.json();

        if (data.error) {
            resultDiv.innerHTML = '<span style="color: var(--negative);">Error: ' + data.error + '</span>';
        } else {
            let html = '<div style="color: var(--positive); font-weight: 700; margin-bottom: 8px;">';
            html += 'Outcome: ' + data.outcome.toUpperCase().replace(/_/g, ' ') + '</div>';

            // XRP distribution
            html += '<div style="margin-bottom: 8px;">XRP Distribution:</div>';
            const dist = data.xrp_distribution;
            if (dist) {
                for (const [key, val] of Object.entries(dist)) {
                    html += '  ' + key + ': ' + val + ' XRP\n';
                }
            }

            // Karma changes
            html += '\nKarma Changes:\n';
            const karma = data.karma_changes;
            if (karma) {
                for (const [key, val] of Object.entries(karma)) {
                    const delta = val.karma_delta;
                    const sign = delta > 0 ? '+' : '';
                    const color = delta > 0 ? 'var(--positive)' : 'var(--negative)';
                    html += '  ' + key + ': <span style="color:' + color + '">' + sign + delta + ' KRM</span> — ' + val.reason + '\n';
                }
            }

            // New scores
            if (data.new_scores) {
                html += '\nUpdated Scores:\n';
                for (const [name, score] of Object.entries(data.new_scores)) {
                    html += '  ' + name + ': ' + Math.floor(score) + ' KRM\n';
                }
            }

            // Tx hashes
            if (data.tx_hashes) {
                html += '\nTransaction Hashes (verify on XRPL Explorer):\n';
                const all = [
                    ...(data.tx_hashes.escrow || []),
                    ...(data.tx_hashes.payments || []),
                    ...(data.tx_hashes.karma || []),
                ];
                for (const hash of all) {
                    if (hash) {
                        html += '  <a href="https://testnet.xrpl.org/transactions/' + hash + '" target="_blank" class="tx-link">' + hash.substring(0, 20) + '...</a>\n';
                    }
                }
            }

            resultDiv.innerHTML = html;

            // Reload page after a short delay to show updated karma
            setTimeout(() => { location.reload(); }, 3000);
        }
    } catch (err) {
        resultDiv.innerHTML = '<span style="color: var(--negative);">Network error: ' + err.message + '</span>';
    } finally {
        buttons.forEach(b => b.disabled = false);
    }
}
