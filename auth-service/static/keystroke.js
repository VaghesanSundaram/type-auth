// keystroke capture and ui helpers

class KeystrokeCapture {
    constructor(keyphrase, options = {}) {
        this.keyphrase = keyphrase;
        this.currentIndex = 0;
        this.timings = [];
        this.lastKeyTime = null;
        this.isActive = true;

        this.onCharacter = options.onCharacter || (() => { });
        this.onMistake = options.onMistake || (() => { });
        this.onComplete = options.onComplete || (() => { });
        this.onReset = options.onReset || (() => { });

        this.handleKeyDown = this.handleKeyDown.bind(this);
        document.addEventListener('keydown', this.handleKeyDown);
    }

    handleKeyDown(event) {
        if (!this.isActive) return;
        if (event.ctrlKey || event.altKey || event.metaKey) return;
        if (event.key === 'Escape') return;

        if (event.key.length === 1 || event.key === ' ') {
            event.preventDefault();
        } else {
            return;
        }

        const expected = this.keyphrase[this.currentIndex];
        const actual = event.key;

        // record interval between keystrokes (seconds)
        const now = performance.now();
        if (this.lastKeyTime !== null) {
            this.timings.push((now - this.lastKeyTime) / 1000);
        }
        this.lastKeyTime = now;

        if (actual === expected) {
            this.currentIndex++;
            this.onCharacter(this.currentIndex - 1, actual);

            if (this.currentIndex >= this.keyphrase.length) {
                this.isActive = false;
                this.onComplete(this.timings.slice());
            }
        } else {
            this.onMistake(expected, actual);
            this.reset();
        }
    }

    reset() {
        this.currentIndex = 0;
        this.timings = [];
        this.lastKeyTime = null;
        this.isActive = true;
        this.onReset();
    }

    destroy() {
        this.isActive = false;
        document.removeEventListener('keydown', this.handleKeyDown);
    }

    pause() { this.isActive = false; }
    resume() { this.isActive = true; }
}


function renderKeyphrase(keyphrase, containerSelector) {
    const container = document.querySelector(containerSelector);
    if (!container) return;

    container.innerHTML = '';

    for (let i = 0; i < keyphrase.length; i++) {
        const span = document.createElement('span');
        span.className = 'char pending';
        span.dataset.index = i;
        span.innerHTML = keyphrase[i] === ' ' ? '&nbsp;' : keyphrase[i];
        container.appendChild(span);
    }

    updateCurrentChar(0);
}

function updateCharState(index, state) {
    const el = document.querySelector(`.char[data-index="${index}"]`);
    if (el) el.className = `char ${state}`;
}

function markCharTyped(index) {
    updateCharState(index, 'typed');
    if (index + 1 < document.querySelectorAll('.char').length) {
        updateCurrentChar(index + 1);
    }
}

function updateCurrentChar(index) {
    document.querySelectorAll('.char.current').forEach(el => {
        if (!el.classList.contains('typed')) el.className = 'char pending';
    });

    const el = document.querySelector(`.char[data-index="${index}"]`);
    if (el && !el.classList.contains('typed')) el.className = 'char current';
}

function flashError(index) {
    const el = document.querySelector(`.char[data-index="${index}"]`);
    if (el) {
        el.classList.add('error');
        setTimeout(() => el.classList.remove('error'), 300);
    }
}

function resetKeyphrase() {
    document.querySelectorAll('.char').forEach(el => {
        el.className = 'char pending';
    });
    updateCurrentChar(0);
}

function updateProgress(current, total) {
    const fill = document.querySelector('.progress-fill');
    const label = document.querySelector('.progress-current');
    if (fill) fill.style.width = `${(current / total) * 100}%`;
    if (label) label.textContent = current;
}

function showStatus(message, type = 'info') {
    const el = document.querySelector('.status');
    if (el) {
        el.textContent = message;
        el.className = `status ${type}`;
    }
}

function hideStatus() {
    const el = document.querySelector('.status');
    if (el) el.className = 'status hidden';
}

function showLoading(show = true) {
    const el = document.querySelector('.loading-overlay');
    if (el) el.classList.toggle('visible', show);
}
