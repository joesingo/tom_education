const AJAX_ACTIONS = {
    'create_timelapse': true,
    'pipeline': true
};
var $FORM = $('#dataproduct-action-form');
var $PIPELINE_SELECT = $('#pipeline-select');
var $PIPELINE_HIDDEN = $('input[name=pipeline_name]');

// Timestamp from the first API response: use this to determine whether a
// process completed before our first request, in which case we do not show it
var first_api_response_time = null;

/*
 * Start periodically polling the API to get info on processes for the given
 * target
 */
function startStatusPolling(target_pk) {
    var process_statuses = null;

    window.setInterval(function() {
        // TODO: don't hardcode URL
        var url = '/api/async/status/' + target_pk + '/';
        $.get(url, function(data) {
            if (first_api_response_time === null) {
                first_api_response_time = data.timestamp;
            }
            if (JSON.stringify(process_statuses) !== JSON.stringify(data)) {
                process_statuses = data;
                showProcesses(process_statuses.processes);
            }
        }, 'json').fail(function() {
            showError('Failed to retrieve process statuses');
        });
    }, AJAX_POLL_INTERVAL);
}

/*
 * Display the status of processes. `obj` is the 'processes' attribute in the
 * JSON API response
 */
function showProcesses(obj) {
    var $wrapper = $('#async-table-wrapper');
    var $loading = $wrapper.find("#loading");
    var $empty_message = $wrapper.find("#no-processes");
    var $table = $wrapper.find('table');
    var $tbody = $table.find('tbody');
    $tbody.html('');

    var no_processes = true;
    for (var i=0; i<obj.length; i++) {
        var process = obj[i];
        if (process.terminal_timestamp && process.terminal_timestamp < first_api_response_time) {
            continue;
        }
        no_processes = false;
        var $row = $('<tr>');
        $row.append('<td>' + process.identifier + '</td>');
        $row.append('<td>' + getDateString(process.created) + '</td>');
        var status_text = '<b>' + capitaliseFirst(process.status) + '</b>';
        if (process.view_url) {
            status_text += ` (<a href="${process.view_url}" title="View process details">View</a>)`;
        }
        var $status_cell = $('<td>' + status_text + '</td>');
        if (process.status == 'created') {
            $status_cell.append(' (refresh to view in data table)');
        }
        else if (process.status === 'failed' && process.failure_message) {
            $status_cell.append(' (' + process.failure_message + ')');
        }
        $row.append($status_cell);
        $tbody.append($row);
    }

    $loading.hide();
    if (no_processes) {
        $table.hide();
        $empty_message.show();
    }
    else {
        $table.show();
        $empty_message.hide();
    }
}

/*
 * Submit handler for action form so we can perform some actions asynchronously
 */
$FORM.submit(function(event) {
    var action = $FORM.find('input[type=submit][clicked=true]').attr('name');
    $FORM.find('input[name=action]').val(action);
    if (!(action in AJAX_ACTIONS)) {
        return;
    }
    event.preventDefault();

    if (action === 'pipeline') {
        var pipeline_name = $PIPELINE_SELECT.val();
        if (!pipeline_name) {
            $PIPELINE_SELECT.addClass('is-invalid');
            console.warn('No pipeline name selected');
            return;
        }
        $PIPELINE_SELECT.removeClass('is-invalid');
        $PIPELINE_HIDDEN.val(pipeline_name);
    }

    $.post($FORM.attr('action'), $FORM.serialize() , function(data) {
        deselectAllProducts();
        // Scroll to async section
        window.location.href = '#async-section';
    },
    'json').fail(function() {
        showError('Failed to submit form');
    });
});

/*
 * Set a 'clicked' attribute on submit inputs when they are clicked, so that we
 * can determine which action should be taken on form submission. Inspired by
 * this: https://stackoverflow.com/a/5721762
 */
$FORM.find('input[type=submit]').click(function() {
    $FORM.find('input[type=submit]').removeAttr('clicked');
    $(this).attr('clicked', 'true');
});

/*
 * Populate the pipeline fieldset with pipeline-specific flags when dropdown is
 * changed
 */
$PIPELINE_SELECT.change(function() {
    // Disable all checkboxes to avoid clashes if different pipelines use the
    // same flag names
    $FORM.find('fieldset input').attr('disabled', true);
    $FORM.find('fieldset').hide();
    var pipeline_name = $(this).val();
    $f = $FORM.find(`fieldset#${pipeline_name}-flags`);
    if ($f.length > 0) {
        $f.find('input').attr('disabled', false);
        $f.show();
    }
});

startStatusPolling($FORM.data('target'));
