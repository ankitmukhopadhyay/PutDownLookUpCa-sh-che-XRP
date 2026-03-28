// PUT UP — Frontend JavaScript

// ── GPS Helpers ──────────────────────────────────────────────────

function getLocation() {
    return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            reject(new Error('Geolocation is not supported by this browser'));
            return;
        }
        // Try high accuracy first, fall back to low accuracy if unavailable
        navigator.geolocation.getCurrentPosition(resolve, function(err) {
            if (err.code === err.POSITION_UNAVAILABLE) {
                navigator.geolocation.getCurrentPosition(resolve, reject, {
                    enableHighAccuracy: false,
                    timeout: 15000,
                });
            } else {
                reject(err);
            }
        }, {
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

    const email = document.getElementById('email-input')?.value.trim() || '';
    if (!email || !email.includes('@')) { alert('Enter a valid email address.'); return; }

    const password = document.getElementById('password-input')?.value || '';
    if (password.length < 6) { alert('Password must be at least 6 characters.'); return; }

    const btn = document.getElementById('register-btn');
    const resultDiv = document.getElementById('register-result');
    btn.disabled = true;
    btn.textContent = 'Creating wallet...';
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = '<span class="spinner"></span> Setting up your XRPL wallet...';

    try {
        const resp = await fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, email, password, deposit_xrp: 0 }),
        });
        const data = await resp.json();
        if (data.error) {
            resultDiv.innerHTML = `<span style="color:var(--negative)">Error: ${data.error}</span>`;
            btn.disabled = false;
            btn.textContent = 'Create Wallet';
        } else {
            window.location.href = data.profile_url;
        }
    } catch (e) {
        resultDiv.innerHTML = `<span style="color:var(--negative)">Network error: ${e.message}</span>`;
        btn.disabled = false;
        btn.textContent = 'Create Wallet';
    }
}

// ── Event Creation ────────────────────────────────────────────────
// createEvent() is defined inline in event_create.html for access to USERS balance data

// ── Add Funds (Top-Up) ────────────────────────────────────────────

async function addFunds(address) {
    const topupXrp = parseFloat(document.getElementById('topup-amount').value) || 0;
    if (topupXrp <= 0) { alert('Enter an amount greater than 0.'); return; }

    const btn = document.querySelector('[onclick*="addFunds"]');
    const resultDiv = document.getElementById('topup-result');
    btn.disabled = true;
    btn.textContent = 'Redirecting to payment...';
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = '<span class="spinner"></span> Opening Stripe checkout...';

    try {
        const resp = await fetch('/api/stripe/topup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address, topup_xrp: topupXrp }),
        });
        const data = await resp.json();
        if (data.error) {
            resultDiv.innerHTML = `<span style="color:var(--negative)">${data.error}</span>`;
            btn.disabled = false;
            btn.textContent = 'Add Funds via Stripe';
        } else {
            window.location.href = data.url;
        }
    } catch (e) {
        resultDiv.innerHTML = `<span style="color:var(--negative)">Network error: ${e.message}</span>`;
        btn.disabled = false;
        btn.textContent = 'Add Funds via Stripe';
    }
}

// ── GPS Check-In ──────────────────────────────────────────────────

async function doCheckin(address, eventId) {
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
                event_id: eventId,
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

async function resolveEvent(eventId, btn) {
    const resultDiv = document.getElementById('resolve-result-' + eventId);
    resultDiv.classList.remove('hidden');
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<span class="spinner"></span> Resolving on XRPL Testnet... (15–30 seconds)';
    btn.disabled = true;

    try {
        const resp = await fetch('/api/event/resolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event_id: eventId }),
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
                    if (hash) html += `  <span class="tx-link">${hash.substring(0, 20)}...</span>\n`;
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
                        html += '  <span class="tx-link">' + hash.substring(0, 20) + '...</span>\n';
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
