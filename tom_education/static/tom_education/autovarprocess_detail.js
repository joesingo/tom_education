const URL = '/autovar/logs/' + AUTOVAR_PROCESS_PK;
var $CREATED      = $('#process-created');
var $STATUS       = $('#process-status');
var $FINISHED     = $('#process-finished');
var $FOLLOW_LOGS  = $('#follow-logs')[0];
var $LOGS_WRAPPER = $('pre.logs');
var $LOGS         = $LOGS_WRAPPER.find('code');

window.setInterval(function() {
    $.get(URL, function(data) {
        if (!data.ok) {
            showError('An error occurred: ' + data.error);
            return;
        }
        $CREATED.text(getDateString(data.created));
        var status_text = capitaliseFirst(data.status);
        if (data.status === 'failed' && data.failure_message) {
            status_text += ` (${data.failure_message})`;
        }
        $STATUS.text(status_text);
        var finished_text = data.terminal_timestamp ? getDateString(data.terminal_timestamp) : 'N/A';
        $FINISHED.text(finished_text);
        $LOGS.text(data.logs);

        if ($FOLLOW_LOGS.checked) {
            $LOGS_WRAPPER.animate({
                'scrollTop': $LOGS.height(),
            }, 1000, 'linear');
        }
    }, 'json').fail(function() {
        showError('Failed to retrieve process information');
    });
}, AJAX_POLL_INTERVAL);
