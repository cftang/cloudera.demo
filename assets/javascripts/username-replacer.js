(function() {
    const PLACEHOLDER = "USERNAME";
    const STORAGE_KEY = "mkdocs_user_username";
    const REGEX = new RegExp(PLACEHOLDER, 'g');

    // Helper: Recursively walk through DOM nodes to find and replace text within TextNodes only.
    // This ensures we don't break surrounding span tags used for syntax highlighting.
    function walkAndReplace(node, replacementText) {
        if (node.nodeType === Node.TEXT_NODE) {
            // If this text node contains the placeholder, replace it
            if (node.nodeValue.includes(PLACEHOLDER)) {
                node.nodeValue = node.nodeValue.replace(REGEX, replacementText);
            }
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            // If it's an element (like a syntax highlight span), explore its children
            Array.from(node.childNodes).forEach(child => {
                walkAndReplace(child, replacementText);
            });
        }
    }

    // 1. Initialization: Find blocks containing the placeholder and store their original HTML structure.
    function initCodeBlocks() {
        // We target all <code> elements (both block-level in <pre> and inline)
        const codeBlocks = document.querySelectorAll('code');

        codeBlocks.forEach(block => {
            // Check if the raw text contains the placeholder before we do expensive DOM work
            if (block.textContent.includes(PLACEHOLDER) && !block.hasAttribute('data-original-html')) {
                // IMPORTANT: We save innerHTML now, not textContent, to preserve syntax highlighting spans.
                block.setAttribute('data-original-html', block.innerHTML);
            }
        });
    }

    // 2. The Replacement Logic
    function updateCodeBlocks(username) {
        const targetBlocks = document.querySelectorAll('code[data-original-html]');

        targetBlocks.forEach(block => {
            // A. Always RESET to the original HTML structure first.
            // This brings back the placeholder and all original syntax highlighting spans.
            block.innerHTML = block.getAttribute('data-original-html');

            // B. If we have a valid username to insert, perform the surgical replacement
            if (username && username.trim() !== '') {
                 // We use the recursive helper to avoid breaking HTML tags
                 walkAndReplace(block, username);
            }
            // If no username exists, we already reset to placeholder in step A, so we are done.
        });
    }

    // 3. Handle User Input (UI listeners)
    function setupEventListeners() {
        const inputField = document.getElementById('user-username-input');
        const saveButton = document.getElementById('user-username-save');
        const clearButton = document.getElementById('user-username-clear');

        if (!inputField || !saveButton) return;

        const savedUsername = localStorage.getItem(STORAGE_KEY);
        if (savedUsername) {
            inputField.value = savedUsername;
        }

        saveButton.addEventListener('click', function() {
            const val = inputField.value;
            // Even if empty, save it to allow clearing via the input box
            localStorage.setItem(STORAGE_KEY, val);
            updateCodeBlocks(val);
        });

        if(clearButton) {
            clearButton.addEventListener('click', function() {
                localStorage.removeItem(STORAGE_KEY);
                inputField.value = "";
                updateCodeBlocks(null); // passing null triggers reset to placeholder
            });
        }
    }


    // 4. Main Execution and navigation handling
    function run() {
        initCodeBlocks();
        setupEventListeners();
        const savedUsername = localStorage.getItem(STORAGE_KEY);
        // Always run update. If savedUsername is null, it ensures blocks are in placeholder state.
        updateCodeBlocks(savedUsername);
    }

    // Initial load
    document.addEventListener("DOMContentLoaded", run);

    // Handle navigation in Material theme SPA mode
    if (window.location$) {
        window.location$.subscribe(function() {
            // A slight delay ensures the new page content is loaded into the DOM
            setTimeout(run, 100);
        });
    }

})();