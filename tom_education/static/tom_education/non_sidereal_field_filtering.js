$(document).ready(function() {
    var json_string = $('#non-sidereal-fields-json')[0].textContent;
    var field_info = JSON.parse(json_string).non_sidereal_fields;

    var $scheme_dropdown = $('#id_scheme');
    var $form = $scheme_dropdown.parents('form');
    // Build a mapping from name to <input>s
    var inputs = {};
    var $all_inputs = $form.find('input').not('[type=hidden]').filter(function() {
        var id = $(this).attr('id');
        return id.startsWith('id_') && !(id.startsWith('id_targetextra'));  // Exclude 'tag' inputs
    });
    $all_inputs.each(function(i) {
        var name = $(this).attr('name');
        inputs[name] = this;
    });

    $scheme_dropdown.on('change', function() {
        var scheme = $(this).val();
        for (var name in inputs) {
            var $inp = $(inputs[name]);
            var required = (scheme ? field_info.scheme_fields[scheme] : []);

            // This field should be hidden iff it is not a base field and not
            // required for the selected scheme
            var hidden = field_info.base_fields.indexOf(name) < 0 && required.indexOf(name) < 0;
            // Note: hide the *parent* instead of the input itself, so that
            // label and help text is also hidden
            $inp.parent().attr('hidden', hidden);
        }
    });

    // Trigger a change to the dropdown straight away
    $scheme_dropdown.trigger('change');
});
