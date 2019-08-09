const PRODUCT_CHECKBOXES_SELECTOR = 'input.dataproduct-checkbox';

function deselectAllProducts() {
    $(PRODUCT_CHECKBOXES_SELECTOR).prop('checked', false);
}

function selectAllProducts(reduced_only) {
    deselectAllProducts();
    var selector = PRODUCT_CHECKBOXES_SELECTOR;
    if (reduced_only) {
        selector += '.reduced';
    }
    $(selector).prop('checked', true);
}

function selectGroup() {
    deselectAllProducts();
    var selector = PRODUCT_CHECKBOXES_SELECTOR;
    var group_pk = $('#dp-group-select').val();
    if (!group_pk) {
        return;
    }
    selector += '.dpgroup-' + group_pk;
    $(selector).prop('checked', true);
}
