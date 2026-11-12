// A dropdown marked data-autosubmit reloads the page when it changes (the Compare pickers
// and the Insights product-type selector). data-resets lists the fields below it (by name)
// to empty first, so a new category or brand does not carry a product from the old list.
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
