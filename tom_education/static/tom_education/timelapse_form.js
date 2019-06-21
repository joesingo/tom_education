function selectAllProducts(reduced_only) {
    // Uncheck all boxes first
    var all_boxes = 'input.timelapse-checkbox';
    $(all_boxes).prop('checked', false);

    var selector = all_boxes;
    if (reduced_only) {
        selector += '.reduced';
    }
    $(selector).prop('checked', true);
}
