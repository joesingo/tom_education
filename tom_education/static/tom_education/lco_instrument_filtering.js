$(document).ready(function() {
    var json_string = $('#instrument-filters-json')[0].textContent;
    var instrument_filters = JSON.parse(json_string).instrument_filters;

    var $instrument_type_dropown = $('#id_instrument_type');
    var $filter_rows = $('table#filters-table tbody tr');

    $instrument_type_dropown.on('change', function() {
        // Get instrument code and available filters
        var instr_code = $(this).val();
        var filters = instrument_filters[instr_code];

        // Loop through filter rows and hide ones that are not available for
        // the instrument
        $filter_rows.each(function(i) {
            var $row = $(this);
            var filter_code = $row.data('code');
            var hidden = (filters.indexOf(filter_code) < 0);
            $row.attr('hidden', hidden);
            // Also set disabled state of inputs in this row
            $row.find('input').attr('disabled', hidden);
        });
    });

    // Trigger a dropdown change to initialise table
    $instrument_type_dropown.trigger('change');
});
