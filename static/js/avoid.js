// "Ingredients to avoid" in the Products filter. The list lives only in this browser: a cookie
// that this script sets when the visitor adds, removes or clears words. The server reads the
// cookie to filter and tag the page; it does not save it, log it or put it in a link. The server
// checks every word again, so the check here only gives quick feedback.
(function () {
    var script = document.currentScript;
    var panel = document.getElementById("avoid-filter");
    if (!script || !panel) {
        return;
    }
    var NAME = script.dataset.cookie;
    var DAYS = parseInt(script.dataset.days, 10);
    var MAX_TERMS = parseInt(script.dataset.maxTerms, 10);
    var MIN_LENGTH = parseInt(script.dataset.minLength, 10);
    var MAX_LENGTH = parseInt(script.dataset.maxLength, 10);

    var input = document.getElementById("avoid-input");
    var addButton = document.getElementById("avoid-add");
    var error = document.getElementById("avoid-error");
    var clearButton = document.getElementById("avoid-clear");

    // a link such as /products#avoid-filter opens the section even when the list is empty
    if (location.hash === "#avoid-filter") {
        panel.open = true;
    }

    function readList() {
        var prefix = NAME + "=";
        var entry = document.cookie.split("; ").filter(function (part) {
            return part.indexOf(prefix) === 0;
        })[0];
        if (!entry) {
            return [];
        }
        try {
            var list = JSON.parse(decodeURIComponent(entry.slice(prefix.length)));
            return Array.isArray(list) ? list.filter(function (t) { return typeof t === "string"; }) : [];
        } catch (e) {
            return [];
        }
    }

    function writeList(list) {
        var secure = location.protocol === "https:" ? "; Secure" : "";
        if (list.length === 0) {
            document.cookie = NAME + "=; max-age=0; path=/; SameSite=Lax" + secure;
        } else {
            document.cookie = NAME + "=" + encodeURIComponent(JSON.stringify(list)) +
                "; max-age=" + DAYS * 86400 + "; path=/; SameSite=Lax" + secure;
        }
        // back to the first page of the same search, so the page shows the new list
        var url = new URL(location.href);
        url.searchParams.delete("page");
        url.hash = "";
        location.assign(url.toString());
    }

    function usable(text) {
        return text.length >= MIN_LENGTH && text.length <= MAX_LENGTH &&
            /^(?:[\p{L}\p{N}]|[ .'\/()+-])+$/u.test(text) &&
            /[\p{L}\p{N}]/u.test(text) &&
            !/[\p{L}\p{N}]\.[\p{L}\p{N}]/u.test(text);
    }

    function addWord() {
        var text = input.value.trim().replace(/\s+/g, " ").toLowerCase();
        var list = readList();
        if (!usable(text) || (list.indexOf(text) === -1 && list.length >= MAX_TERMS)) {
            error.hidden = false;
            return;
        }
        error.hidden = true;
        if (list.indexOf(text) === -1) {
            list.push(text);
        }
        writeList(list);
    }

    addButton.addEventListener("click", addWord);

    // Enter in the box adds the word; it must not run the product search
    input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
            event.preventDefault();
            addWord();
        }
    });

    panel.addEventListener("click", function (event) {
        var button = event.target.closest("[data-remove]");
        if (button) {
            writeList(readList().filter(function (term) { return term !== button.dataset.remove; }));
        }
    });

    if (clearButton) {
        clearButton.addEventListener("click", function () {
            writeList([]);
        });
    }
})();
