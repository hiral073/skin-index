// A dropdown marked data-autosubmit reloads the page when it changes (the Compare pickers
// and the Insights product-type selector). data-resets lists the fields below it (by name)
// to empty first, so a new category or main ingredient does not carry a product from the old list.
// Without JavaScript the visible "Show" button next to the dropdown does the same thing.
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("select[data-autosubmit]").forEach(function (select) {
        select.addEventListener("change", function () {
            var form = select.form;
            (select.dataset.resets || "").split(/\s+/).filter(Boolean).forEach(function (name) {
                if (form.elements[name]) {
                    form.elements[name].value = "";
                }
            });
            form.submit();
        });
    });
});

// Mobile menu: this script adds the menu button, so without JavaScript the links are simply always shown.
document.addEventListener("DOMContentLoaded", function () {
    var bar = document.querySelector(".navbar");
    var links = document.getElementById("site-menu");
    if (!bar || !links) {
        return;
    }
    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "nav-toggle";
    toggle.setAttribute("aria-label", "Menu");
    toggle.setAttribute("aria-controls", "site-menu");
    toggle.setAttribute("aria-expanded", "false");
    toggle.innerHTML = '<span class="nav-toggle-bar" aria-hidden="true"></span>';
    links.parentNode.insertBefore(toggle, links);
    function setOpen(open) {
        bar.classList.toggle("is-open", open);
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
    toggle.addEventListener("click", function () {
        setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
            setOpen(false);
            toggle.focus();
        }
    });
});
