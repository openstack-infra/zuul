// Client script for Zuul status page
//
// Copyright 2012 OpenStack Foundation
// Copyright 2013 Timo Tijhof
// Copyright 2013 Wikimedia Foundation
// Copyright 2014 Rackspace Australia
//
// Licensed under the Apache License, Version 2.0 (the "License"); you may
// not use this file except in compliance with the License. You may obtain
// a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
// WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
// License for the specific language governing permissions and limitations
// under the License.
'use strict';

(function ($) {
    var $container, $msg, $indicator, $queueInfo, $queueEventsNum,
        $queueResultsNum, $pipelines, $jq;
    var xhr, zuul,
        current_filter = '',
        demo = location.search.match(/[?&]demo=([^?&]*)/),
        source_url = location.search.match(/[?&]source_url=([^?&]*)/),
        source = demo ?
            './status-' + (demo[1] || 'basic') + '.json-sample' :
            'status.json';
    source = source_url ? source_url[1] : source;

    function set_cookie(name, value) {
        document.cookie = name + '=' + value + '; path=/';
    }

    function read_cookie(name, default_value) {
        var nameEQ = name + '=';
        var ca = document.cookie.split(';');
        for(var i=0;i < ca.length;i++) {
            var c = ca[i];
            while (c.charAt(0) === ' ') {
                c = c.substring(1, c.length);
            }
            if (c.indexOf(nameEQ) === 0) {
                return c.substring(nameEQ.length, c.length);
            }
        }
        return default_value;
    }


    zuul = {
        enabled: true,
        collapsed_exceptions: [],

        schedule: function () {
            if (!zuul.enabled) {
                setTimeout(zuul.schedule, 5000);
                return;
            }
            zuul.update().complete(function () {
                setTimeout(zuul.schedule, 5000);
            });
        },

        /** @return {jQuery.Promise} */
        update: function () {
            // Cancel the previous update if it hasn't completed yet.
            if (xhr) {
                xhr.abort();
            }

            zuul.emit('update-start');

            xhr = $.getJSON(source)
                .done(function (data) {
                    if ('message' in data) {
                        $msg.removeClass('alert-danger').addClass('alert-info');
                        $msg.text(data.message);
                        $msg.show();
                    } else {
                        $msg.empty();
                        $msg.hide();
                    }

                    if ('zuul_version' in data) {
                        $('#zuul-version-span').text(data.zuul_version);
                    }
                    if ('last_reconfigured' in data) {
                        var last_reconfigured =
                            new Date(data.last_reconfigured);
                        $('#last-reconfigured-span').text(
                            last_reconfigured.toString());
                    }

                    $pipelines.html('');
                    $.each(data.pipelines, function (i, pipeline) {
                        $pipelines.append(zuul.format.pipeline(pipeline));
                    });

                    $queueEventsNum.text(
                        data.trigger_event_queue ?
                            data.trigger_event_queue.length : '0'
                    );
                    $queueResultsNum.text(
                        data.result_event_queue ?
                            data.result_event_queue.length : '0'
                    );
                })
                .fail(function (err, jqXHR, errMsg) {
                    $msg.text(source + ': ' + errMsg).show();
                    $msg.removeClass('zuul-msg-wrap-off');
                })
                .complete(function () {
                    xhr = undefined;
                    zuul.emit('update-end');
                });

            return xhr;
        },

        format: {
            job: function(job) {
                var $job_line;
                if (job.url !== null) {
                    $job_line = $('<a href="' + job.url + '" />');
                }
                else{
                    $job_line = $('<span />');
                }
                $job_line.text(job.name)
                    .append(zuul.format.job_status(job));

                if (job.voting === false) {
                    $job_line.append(
                        $(' <small />').text(' (non-voting)')
                    );
                }
                return $job_line;
            },

            job_status: function(job) {
                var result = job.result ? job.result.toLowerCase() : null;
                if (result === null) {
                    result = job.url ? 'in progress' : 'queued';
                }

                if (result === 'in progress') {
                    return zuul.format.job_progress_bar(job.elapsed_time,
                                                        job.remaining_time);
                }
                else {
                    return zuul.format.status_label(result);
                }
            },

            status_label: function(result) {
                var $status = $('<span />');
                $status.addClass('zuul-job-result label');

                switch (result) {
                    case 'success':
                        $status.addClass('label-success');
                        break;
                    case 'failure':
                        $status.addClass('label-danger');
                        break;
                    case 'unstable':
                        $status.addClass('label-warning');
                        break;
                    case 'in progress':
                    case 'queued':
                    case 'lost':
                        $status.addClass('label-default');
                        break;
                }
                $status.text(result);
                return $status;
            },

            job_progress_bar: function(elapsed_time, remaining_time) {
                var progress_percent = 100 * (elapsed_time / (elapsed_time +
                                                              remaining_time));
                var $bar_inner = $('<div />')
                    .addClass('progress-bar')
                    .attr('role', 'progressbar')
                    .attr('aria-valuenow', 'progressbar')
                    .attr('aria-valuemin', progress_percent)
                    .attr('aria-valuemin', '0')
                    .attr('aria-valuemax', '100')
                    .css('width', progress_percent + '%');

                var $bar_outter = $('<div />')
                    .addClass('progress zuul-job-result')
                    .append($bar_inner);

                return $bar_outter;
            },

            enqueue_time: function(ms) {
                // Special format case for enqueue time to add style
                var hours = 60 * 60 * 1000;
                var now = Date.now();
                var delta = now - ms;
                var status = 'text-success';
                var text = zuul.format.time(delta, true);
                if (delta > (4 * hours)) {
                    status = 'text-danger';
                } else if (delta > (2 * hours)) {
                    status = 'text-warning';
                }
                return '<span class="' + status + '">' + text + '</span>';
            },

            time: function(ms, words) {
                if (typeof(words) === 'undefined') {
                    words = false;
                }
                var seconds = (+ms)/1000;
                var minutes = Math.floor(seconds/60);
                var hours = Math.floor(minutes/60);
                seconds = Math.floor(seconds % 60);
                minutes = Math.floor(minutes % 60);
                var r = '';
                if (words) {
                    if (hours) {
                        r += hours;
                        r += ' hr ';
                    }
                    r += minutes + ' min';
                } else {
                    if (hours < 10) {
                        r += '0';
                    }
                    r += hours + ':';
                    if (minutes < 10) {
                        r += '0';
                    }
                    r += minutes + ':';
                    if (seconds < 10) {
                        r += '0';
                    }
                    r += seconds;
                }
                return r;
            },

            change_total_progress_bar: function(change) {
                var job_percent = Math.floor(100 / change.jobs.length);
                var $bar_outter = $('<div />')
                    .addClass('progress zuul-change-total-result');

                $.each(change.jobs, function (i, job) {
                    var result = job.result ? job.result.toLowerCase() : null;
                    if (result === null) {
                        result = job.url ? 'in progress' : 'queued';
                    }

                    if (result !== 'queued') {
                        var $bar_inner = $('<div />')
                            .addClass('progress-bar');

                        switch (result) {
                            case 'success':
                                $bar_inner.addClass('progress-bar-success');
                                break;
                            case 'lost':
                            case 'failure':
                                $bar_inner.addClass('progress-bar-danger');
                                break;
                            case 'unstable':
                                $bar_inner.addClass('progress-bar-warning');
                                break;
                            case 'in progress':
                            case 'queued':
                                break;
                        }
                        $bar_inner.attr('title', job.name)
                            .css('width', job_percent + '%');
                        $bar_outter.append($bar_inner);
                    }
                });
                return $bar_outter;
            },

            change_header: function(change) {
                var change_id = change.id || 'NA';
                if (change_id.length === 40) {
                    change_id = change_id.substr(0, 7);
                }

                var $change_link = $('<small />');
                if (change.url !== null) {
                    $change_link.append(
                        $('<a />').attr('href', change.url).text(change.id)
                    );
                }
                else {
                    $change_link.text(change_id);
                }

                var $change_progress_row_left = $('<div />')
                    .addClass('col-xs-3')
                    .append($change_link);
                var $change_progress_row_right = $('<div />')
                    .addClass('col-xs-9')
                    .append(zuul.format.change_total_progress_bar(change));

                var $change_progress_row = $('<div />')
                    .addClass('row')
                    .append($change_progress_row_left)
                    .append($change_progress_row_right);

                var $project_span = $('<span />')
                    .addClass('change_project')
                    .text(change.project);

                var $left = $('<div />')
                    .addClass('col-xs-8')
                    .append($project_span, $('<br />'), $change_progress_row);

                var remaining_time = zuul.format.time(
                        change.remaining_time, true);
                var enqueue_time = zuul.format.enqueue_time(
                        change.enqueue_time);
                var $remaining_time = $('<small />').addClass('time')
                    .attr('title', 'Remaining Time').html(remaining_time);
                var $enqueue_time = $('<small />').addClass('time')
                    .attr('title', 'Elapsed Time').html(enqueue_time);

                var $right = $('<div />')
                    .addClass('col-xs-4 text-right')
                    .append($remaining_time, $('<br />'), $enqueue_time);

                var $header = $('<div />')
                    .addClass('row')
                    .append($left, $right);
                return $header;
            },

            change_list: function(jobs) {
                var $list = $('<ul />')
                    .addClass('list-group');

                $.each(jobs, function (i, job) {
                    var $item = $('<li />')
                        .addClass('list-group-item')
                        .addClass('zuul-change-job')
                        .append(zuul.format.job(job));
                    $list.append($item);
                });

                return $list;
            },

            change_panel: function (change) {
                var $header = $('<div />')
                    .addClass('panel-heading patchset-header')
                    .append(zuul.format.change_header(change));

                var panel_id = change.id ? change.id.replace(',', '_')
                                         : change.project.replace('/', '_') +
                                           '-' + change.enqueue_time;
                var $panel = $('<div />')
                    .attr('id', panel_id)
                    .addClass('panel panel-default zuul-change')
                    .append($header)
                    .append(zuul.format.change_list(change.jobs));

                $header.click(zuul.toggle_patchset);
                return $panel;
            },

            pipeline: function (pipeline) {
                var $html = $('<div />')
                    .addClass('zuul-pipeline col-md-4')
                    .append($('<h3 />').text(pipeline.name));

                if (typeof pipeline.description === 'string') {
                    $html.append(
                        $('<p />').append(
                            $('<small />').text(pipeline.description)
                        )
                    );
                }

                $.each(pipeline.change_queues,
                       function (queueNum, changeQueue) {
                    $.each(changeQueue.heads, function (headNum, changes) {
                        if (pipeline.change_queues.length > 1 &&
                            headNum === 0) {
                            var name = changeQueue.name;
                            var short_name = name;
                            if (short_name.length > 32) {
                                short_name = short_name.substr(0, 32) + '...';
                            }
                            $html.append(
                                $('<p />')
                                    .text('Queue: ')
                                    .append(
                                        $('<abbr />')
                                            .attr('title', name)
                                            .text(short_name)
                                    )
                            );
                        }
                        $.each(changes, function (changeNum, change) {
                            var $panel = zuul.format.change_panel(change);
                            $html.append($panel);
                            zuul.display_patchset($panel);
                        });
                    });
                });
                return $html;
            },

            filter_form_group: function(default_text) {
                // Update the filter form with a clear button if required

                var $label = $('<label />')
                    .addClass('control-label')
                    .attr('for', 'filter_string')
                    .text('Filters')
                    .css('padding-right', '0.5em');

                var $input = $('<input />')
                    .attr('type', 'text')
                    .attr('id', 'filter_string')
                    .addClass('form-control')
                    .attr('title',
                          'project(s), pipeline(s) or review(s) comma ' +
                          'separated')
                    .attr('value', default_text);

                $input.change(zuul.handle_filter_change);

                var $clear_icon = $('<span />')
                    .addClass('form-control-feedback')
                    .addClass('glyphicon glyphicon-remove-circle')
                    .attr('id', 'filter_form_clear_box')
                    .attr('title', 'clear filter')
                    .css('cursor', 'pointer');

                $clear_icon.click(function() {
                    $('#filter_string').val('').change();
                });

                if (default_text === '') {
                    $clear_icon.hide();
                }

                var $form_group = $('<div />')
                    .addClass('form-group has-feedback')
                    .append($label, $input, $clear_icon);
                return $form_group;
            },

            expand_form_group: function() {
                var expand_by_default = (
                    read_cookie('zuul_expand_by_default', false) === 'true');

                var $checkbox = $('<input />')
                    .attr('type', 'checkbox')
                    .attr('id', 'expand_by_default')
                    .prop('checked', expand_by_default)
                    .change(zuul.handle_expand_by_default);

                var $label = $('<label />')
                    .css('padding-left', '1em')
                    .html('Expand by default: ')
                    .append($checkbox);

                var $form_group = $('<div />')
                    .addClass('checkbox')
                    .append($label);
                return $form_group;
            },

            control_form: function() {
                // Build the filter form filling anything from cookies

                var $control_form = $('<form />')
                    .attr('role', 'form')
                    .addClass('form-inline')
                    .submit(zuul.handle_filter_change);

                $control_form
                    .append(zuul.format.filter_form_group(current_filter))
                    .append(zuul.format.expand_form_group());

                return $control_form;
            },
        },

        emit: function () {
            $jq.trigger.apply($jq, arguments);
            return this;
        },
        on: function () {
            $jq.on.apply($jq, arguments);
            return this;
        },
        one: function () {
            $jq.one.apply($jq, arguments);
            return this;
        },

        toggle_patchset: function(e) {
            // Toggle showing/hiding the patchset when the header is clicked
            // Grab the patchset panel
            var $panel = $(e.target).parents('.zuul-change');
            var $body = $panel.children(':not(.patchset-header)');
            $body.toggle(200);
            var collapsed_index = zuul.collapsed_exceptions.indexOf(
                $panel.attr('id'));
            if (collapsed_index === -1 ) {
                // Currently not an exception, add it to list
                zuul.collapsed_exceptions.push($panel.attr('id'));
            }
            else {
                // Currently an except, remove from exceptions
                zuul.collapsed_exceptions.splice(collapsed_index, 1);
            }
        },

        display_patchset: function($panel, animate) {
            // Determine if to show or hide the patchset and/or the results
            // when loaded

            // See if we should hide the body/results
            var $body = $panel.children(':not(.patchset-header)');
            var expand_by_default = $('#expand_by_default').prop('checked');
            var collapsed_index = zuul.collapsed_exceptions.indexOf(
                $panel.attr('id'));
            if (expand_by_default && collapsed_index === -1 ||
                !expand_by_default && collapsed_index !== -1) {
                // Expand by default, or is an exception
                $body.show(animate);
            }
            else {
                $body.hide(animate);
            }

            // Check if we should hide the whole panel
            var panel_project = $panel.find('.change_project').text()
                .toLowerCase();
            var panel_pipeline = $panel.parents('.zuul-pipeline')
                .children('h3').text().toLowerCase();
            var panel_change = $panel.attr('id');
            if (current_filter !== '') {
                var show_panel = false;
                var filter = current_filter.trim().split(/[\s,]+/);
                $.each(filter, function(index, f_val) {
                    if (f_val !== '') {
                        f_val = f_val.toLowerCase();
                        if (panel_project.indexOf(f_val) !== '-1' ||
                            panel_pipeline.indexOf(f_val) !== '-1' ||
                            panel_change.indexOf(f_val) !== '-1') {
                            show_panel = true;
                        }
                    }
                });
                if (show_panel === true) {
                    $panel.show(animate);
                }
                else {
                    $panel.hide(animate);
                }
            }
            else {
                $panel.show(animate);
            }
        },

        handle_filter_change: function() {
            // Update the filter and save it to a cookie
            current_filter = $('#filter_string').val();
            set_cookie('zuul_filter_string', current_filter);
            if (current_filter === '') {
                $('#filter_form_clear_box').hide();
            }
            else {
                $('#filter_form_clear_box').show();
            }

            $('.zuul-change').each(function(index, obj) {
                var $panel = $(obj);
                zuul.display_patchset($panel, 200);
            });
            return false;
        },

        handle_expand_by_default: function(e) {
            // Handle toggling expand by default
            set_cookie('zuul_expand_by_default', e.target.checked);
            zuul.collapsed_exceptions = [];
            $('.zuul-change').each(function(index, obj) {
                var $panel = $(obj);
                zuul.display_patchset($panel, 200);
            });
        },
    };

    current_filter = read_cookie('zuul_filter_string', current_filter);

    $jq = $(zuul);

    $jq.on('update-start', function () {
        $container.addClass('zuul-container-loading');
        $indicator.addClass('zuul-spinner-on');
    });

    $jq.on('update-end', function () {
        $container.removeClass('zuul-container-loading');
        setTimeout(function () {
            $indicator.removeClass('zuul-spinner-on');
        }, 500);
    });

    $jq.one('update-end', function () {
        // Do this asynchronous so that if the first update adds a message, it
        // will not animate while we fade in the content. Instead it simply
        // appears with the rest of the content.
        setTimeout(function () {
            // Fade in the content
            $container.addClass('zuul-container-ready');
        });
    });

    $(function ($) {
        $msg = $('<div />').addClass('alert').hide();
        $indicator = $('<button class="btn pull-right zuul-spinner">' +
                       'updating ' +
                       '<span class="glyphicon glyphicon-refresh"></span>' +
                       '</button>');
        $queueInfo = $('<p>Queue lengths: <span>0</span> events, ' +
                       '<span>0</span> results.</p>');
        $queueEventsNum = $queueInfo.find('span').eq(0);
        $queueResultsNum = $queueEventsNum.next();

        var $control_form = zuul.format.control_form();

        var $pipelines = $('<div class="row"></div>');
        var $zuulVersion = $('<p>Zuul version: <span id="zuul-version-span">' +
                         '</span></p>');
        var $lastReconf = $('<p>Last reconfigured: ' +
                        '<span id="last-reconfigured-span"></span></p>');

        $container = $('#zuul-container').append($msg, $indicator,
                                                 $queueInfo, $control_form,
                                                 $pipelines, $zuulVersion,
                                                 $lastReconf);

        zuul.schedule();

        $(document).on({
            'show.visibility': function () {
                zuul.enabled = true;
                zuul.update();
            },
            'hide.visibility': function () {
                zuul.enabled = false;
            }
        });
    });
}(jQuery));
