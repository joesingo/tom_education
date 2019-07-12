const POLL_INTERVAL = 1000;  // in milliseconds
const AJAX_ACTIONS = {
    'create_timelapse': true,
    'analyse': true
};
var $FORM = $('#dataproduct-action-form');

// Timestamp from the first API response: use this to determine whether a
// process completed before our first request, in which case we do not show it
var first_api_response_time = null;

function getDisplayStatus(st) {
    return st[0].toUpperCase() + st.substr(1);
}

/*
 * Start periodically polling the API to get info on processes for the given
 * target
 */
function startStatusPolling(target_pk) {
    var process_statuses = null;

    window.setInterval(function() {
        // TODO: don't hardcode URL
        var url = '/async/status/' + target_pk;
        $.get(url, function(data) {
            if (!data.ok) {
                showError('An error occurred: ' + data.error);
                return;
            }
            if (first_api_response_time === null) {
                first_api_response_time = data.timestamp;
            }
            if (JSON.stringify(process_statuses) !== JSON.stringify(data)) {
                process_statuses = data;
                showProcesses(process_statuses.processes);
            }
        }, 'json').fail(function() {
            showError('Failed to retrieve process statuses')
        });
    }, POLL_INTERVAL);
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
        var created = new Date(process.created * 1000);
        var $row = $('<tr>');
        $row.append('<td>' + process.identifier + '</td>');
        $row.append('<td>' + created.toLocaleString() + '</td>');
        var status_text = '<b>' + getDisplayStatus(process.status) + '</b>';
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
 * Display an error message after a failed AJAX request
 */
function showError(msg) {
    // TODO: show the error in the UI
    throw msg;
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
    $.post($FORM.attr('action'), $FORM.serialize() , function(data) {
        if (data.ok) {
            deselectAllProducts();
            // Scroll to async section
            window.location.href = '#async-section';
        }
        else {
            showError('Error submitting form');
        }
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

startStatusPolling($FORM.data('target'));
