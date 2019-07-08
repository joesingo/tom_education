const POLL_INTERVAL = 1000;  // in milliseconds
const DISPLAY_STAUSES = {
    'pending': 'Pending',
    'created': 'Created',
    'failed': 'Failed'
};
var $FORM = $('#dataproduct-action-form');

/*
 * Start periodically polling the API to get info on timelapses for the given
 * target
 */
function startStatusPolling(target_pk) {
    var timelapse_stauses = null;

    window.setInterval(function() {
        // TODO: don't hardcode URL
        var url = '/timelapse/status/' + target_pk;
        $.get(url, function(data) {
            if (!data.ok) {
                showError('An error occurred: ' + data.error);
                return;
            }

            if (JSON.stringify(timelapse_stauses) !== JSON.stringify(data)) {
                timelapse_stauses = data;
                showTimelapses(timelapse_stauses.timelapses);
            }
        }, 'json').fail(function() {
            showError('Failed to retrieve timelapse statuses')
        });
    }, POLL_INTERVAL);
}

/*
 * Display the status of timelapses. `obj` is the 'timelapses' attribute
 * in the JSON API response
 */
function showTimelapses(obj) {
    // Find filenames of data products in the data table, so as to not show
    // created timelapses in two places
    var filenames = {};
    $('.product-filename').each(function(index) {
        filenames[this.innerText] = true;
    });

    var $wrapper = $('#timelapse-table-wrapper');
    var $empty_message = $wrapper.find("p");
    var $table = $wrapper.find('table');
    var $tbody = $table.find('tbody');
    $tbody.html('');

    var no_timelapses = true;
    for (var st in obj) {
        var timelapses = obj[st];
        for (var i=0; i<timelapses.length; i++) {
            var timelapse = timelapses[i];
            if (timelapse.filename in filenames) {
                continue;
            }
            no_timelapses = false;
            var $row = $('<tr>');
            $row.append('<td>' + timelapse.filename + '</td>');
            var $status_cell = $('<td><b>' + DISPLAY_STAUSES[st] + '</b></td>');
            if (st == 'created') {
                $status_cell.append(' (refresh to view in data table)');
            }
            else if (st === 'failed' && timelapse.failure_message) {
                $status_cell.append(' (' + timelapse.failure_message + ')');
            }
            $row.append($status_cell);
            $tbody.append($row);
        }
    }

    if (no_timelapses) {
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
 * Submit handler for action form so we can create timelapses asynchronously
 */
$FORM.submit(function(event) {
    var action = $FORM.find('input[type=submit][clicked=true]').attr('name');
    $FORM.find('input[name=action]').val(action);
    // For any action other than timelapse, submit form as usual
    if (action !== 'create_timelapse') {
        return;
    }

    event.preventDefault();
    $.post($FORM.attr('action'), $FORM.serialize() , function(data) {
        if (data.ok) {
            deselectAllProducts();
            // Scroll to timelapse section
            window.location.href = '#timelapse-section';
        }
        else {
            showError('Error submitting timelapse');
        }
    },
    'json').fail(function() {
        showError('Failed to submit timelapse');
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
