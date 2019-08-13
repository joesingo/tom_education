$(document).ready(function() {
    var json_string = $('#instrument-filters-json')[0].textContent;
    var instrument_filters = JSON.parse(json_string).instrument_filters;

    var $instrument_type_dropown = $('#id_instrument_type');
    var $filter_dropown = $('#id_filter');
    var $filter_options = $filter_dropown.find('option');

    $instrument_type_dropown.on('change', function() {
        // Get instrument code and available filters
        var instr_code = $(this).val();
        var filters = instrument_filters[instr_code];

        // Loop through filter <option> elements, and hide filters that are
        // not available
        var first_available_code = null;
        $filter_options.each(function(i) {
            var $option = $(this);
            var filter_code = $option.val();
            var hidden = (filters.indexOf(filter_code) < 0);

            if (!hidden && !first_available_code) {
                first_available_code = filter_code;
            }
            $option.attr('hidden', hidden);
        });

        $filter_dropown.val(first_available_code || '').change();
    });

    // Trigger a dropdown change to initialise filters dropdown
    $instrument_type_dropown.trigger('change');
});
