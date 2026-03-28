// PUT UP — Frontend JavaScript

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
