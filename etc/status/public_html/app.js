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
        zuul_graph_update_count = 0,
        zuul_sparkline_urls = {},
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
        graphite_url: '',
        collapsed_exceptions: [],

        schedule: function () {
            if (!zuul.enabled) {
                setTimeout(zuul.schedule, 5000);
                return;
            }
            zuul.update().complete(function () {
                setTimeout(zuul.schedule, 5000);
            });

            /* Only update graphs every minute */
            if (zuul_graph_update_count > 11) {
                zuul_graph_update_count = 0;
                zuul.update_sparklines();
            }
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

        update_sparklines: function() {
            $.each(zuul_sparkline_urls, function(name, url) {
                var newimg = new Image();
                var parts = url.split('#');
                newimg.src = parts[0] + '#' + new Date().getTime();
                $(newimg).load(function (x) {
                    zuul_sparkline_urls[name] = newimg.src;
                });
            });
        },

        format: {
            job: function(job) {
                var $job_line = $('<span />');

                if (job.url !== null) {
                    $job_line.append(
                        $('<a />')
                            .addClass('zuul-job-name')
                            .attr('href', job.url)
                            .text(job.name)
                    );
                }
                else {
                    $job_line.append(
                        $('<span />')
                            .addClass('zuul-job-name')
                            .text(job.name)
                    );
                }

                $job_line.append(zuul.format.job_status(job));

                if (job.voting === false) {
                    $job_line.append(
                        $(' <small />')
                            .addClass('zuul-non-voting-desc')
                            .text(' (non-voting)')
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
                    .append($project_span, $change_progress_row);

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
                    .addClass('list-group zuul-patchset-body');

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
                    .addClass('panel-heading zuul-patchset-header')
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

            change_status_icon: function(change) {
                var icon_name = 'green.png';
                var icon_title = 'Succeeding';

                if (change.active !== true) {
                    // Grey icon
                    icon_name = 'grey.png';
                    icon_title = 'Waiting until closer to head of queue to' +
                        ' start jobs';
                }
                else if (change.failing_reasons &&
                         change.failing_reasons.length > 0) {
                    var reason = change.failing_reasons.join(', ');
                    icon_title = 'Failing because ' + reason;
                    if (reason.match(/merge conflict/)) {
                        // Black icon
                        icon_name = 'black.png';
                    }
                    else {
                        // Red icon
                        icon_name = 'red.png';
                    }
                }

                var $icon = $('<img />')
                    .attr('src', 'images/' + icon_name)
                    .attr('title', icon_title)
                    .css('margin-top', '-6px');

                return $icon;
            },

            change_with_status_tree: function(change, change_queue) {
                var $change_row = $('<tr />');

                for (var i = 0; i < change_queue._tree_columns; i++) {
                    var $tree_cell  = $('<td />')
                        .css('height', '100%')
                        .css('padding', '0 0 10px 0')
                        .css('margin', '0')
                        .css('width', '16px')
                        .css('min-width', '16px')
                        .css('overflow', 'hidden')
                        .css('vertical-align', 'top');

                    if (i < change._tree.length && change._tree[i] !== null) {
                        $tree_cell.css('background-image',
                                       'url(\'images/line.png\')')
                            .css('background-repeat', 'repeat-y');
                    }

                    if (i === change._tree_index) {
                        $tree_cell.append(
                            zuul.format.change_status_icon(change));
                    }
                    if (change._tree_branches.indexOf(i) !== -1) {
                        var $image = $('<img />')
                            .css('vertical-align', 'baseline');
                        if (change._tree_branches.indexOf(i) ===
                            change._tree_branches.length - 1) {
                            // Angle line
                            $image.attr('src', 'images/line-angle.png');
                        }
                        else {
                            // T line
                            $image.attr('src', 'images/line-t.png');
                        }
                        $tree_cell.append($image);
                    }
                    $change_row.append($tree_cell);
                }

                var change_width = 360 - 16*change_queue._tree_columns;
                var $change_column = $('<td />')
                    .css('width', change_width + 'px')
                    .addClass('zuul-change-cell')
                    .append(zuul.format.change_panel(change));

                $change_row.append($change_column);

                var $change_table = $('<table />')
                    .addClass('zuul-change-box')
                    .css('-moz-box-sizing', 'content-box')
                    .css('box-sizing', 'content-box')
                    .append($change_row);

                return $change_table;
            },

            pipeline_sparkline: function(pipeline_name) {
                if (zuul.graphite_url !== '') {
                    var $sparkline = $('<img />')
                        .addClass('pull-right')
                        .attr('src', zuul.get_sparkline_url(pipeline_name));
                    return $sparkline;
                }
                return false;
            },

            pipeline_header: function(pipeline, count) {
                // Format the pipeline name, sparkline and description
                var $header_div = $('<div />')
                    .addClass('zuul-pipeline-header');

                var $heading = $('<h3 />')
                    .css('vertical-align', 'middle')
                    .text(pipeline.name)
                    .append(
                        $('<span />')
                            .addClass('badge pull-right')
                            .css('vertical-align', 'middle')
                            .css('margin-top', '0.5em')
                            .text(count)
                    )
                    .append(zuul.format.pipeline_sparkline(pipeline.name));

                $header_div.append($heading);

                if (typeof pipeline.description === 'string') {
                    $header_div.append(
                        $('<p />').append(
                            $('<small />').text(pipeline.description)
                        )
                    );
                }
                return $header_div;
            },

            pipeline: function (pipeline) {
                var count = zuul.create_tree(pipeline);
                var $html = $('<div />')
                    .addClass('zuul-pipeline col-md-4')
                    .append(zuul.format.pipeline_header(pipeline, count));

                $.each(pipeline.change_queues,
                       function (queue_i, change_queue) {
                    $.each(change_queue.heads, function (head_i, changes) {
                        if (pipeline.change_queues.length > 1 &&
                            head_i === 0) {
                            var name = change_queue.name;
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

                        $.each(changes, function (change_i, change) {
                            var $change_box =
                                zuul.format.change_with_status_tree(
                                    change, change_queue);
                            $html.append($change_box);
                            zuul.display_patchset($change_box);
                        });
                    });
                });
                return $html;
            },

            filter_form_group: function() {
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
                    .attr('value', current_filter);

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

                if (current_filter === '') {
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
                    .append(zuul.format.filter_form_group())
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
            var $body = $panel.children('.zuul-patchset-body');
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

        display_patchset: function($change_box, animate) {
            // Determine if to show or hide the patchset and/or the results
            // when loaded

            // See if we should hide the body/results
            var $panel = $change_box.find('.zuul-change');
            var panel_change = $panel.attr('id');
            var $body = $panel.children('.zuul-patchset-body');
            var expand_by_default = $('#expand_by_default').prop('checked');

            var collapsed_index = zuul.collapsed_exceptions.indexOf(panel_change);

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


            var panel_pipeline = $change_box
                .parents('.zuul-pipeline')
                .find('.zuul-pipeline-header > h3')
                .html()
                .toLowerCase();

            if (current_filter !== '') {
                var show_panel = false;
                var filter = current_filter.trim().split(/[\s,]+/);
                $.each(filter, function(index, f_val) {
                    if (f_val !== '') {
                        f_val = f_val.toLowerCase();
                        if (panel_project.indexOf(f_val) !== -1 ||
                            panel_pipeline.indexOf(f_val) !== -1 ||
                            panel_change.indexOf(f_val) !== -1) {
                            show_panel = true;
                        }
                    }
                });
                if (show_panel === true) {
                    $change_box.show(animate);
                }
                else {
                    $change_box.hide(animate);
                }
            }
            else {
                $change_box.show(animate);
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

            $('.zuul-change-box').each(function(index, obj) {
                var $change_box = $(obj);
                zuul.display_patchset($change_box, 200);
            });
            return false;
        },

        handle_expand_by_default: function(e) {
            // Handle toggling expand by default
            set_cookie('zuul_expand_by_default', e.target.checked);
            zuul.collapsed_exceptions = [];
            $('.zuul-change-box').each(function(index, obj) {
                var $change_box = $(obj);
                zuul.display_patchset($change_box, 200);
            });
        },

        create_tree: function(pipeline) {
            var count = 0;
            var pipeline_max_tree_columns = 1;
            $.each(pipeline.change_queues, function(change_queue_i,
                                                       change_queue) {
                var tree = [];
                var max_tree_columns = 1;
                var changes = [];
                var last_tree_length = 0;
                $.each(change_queue.heads, function(head_i, head) {
                    $.each(head, function(change_i, change) {
                        changes[change.id] = change;
                        change._tree_position = change_i;
                    });
                });
                $.each(change_queue.heads, function(head_i, head) {
                    $.each(head, function(change_i, change) {
                        count += 1;
                        var idx = tree.indexOf(change.id);
                        if (idx > -1) {
                            change._tree_index = idx;
                            // remove...
                            tree[idx] = null;
                            while (tree[tree.length - 1] === null) {
                                tree.pop();
                            }
                        } else {
                            change._tree_index = 0;
                        }
                        change._tree_branches = [];
                        change._tree = [];
                        if (typeof(change.items_behind) === 'undefined') {
                            change.items_behind = [];
                        }
                        change.items_behind.sort(function(a, b) {
                            return (changes[b]._tree_position -
                                    changes[a]._tree_position);
                        });
                        $.each(change.items_behind, function(i, id) {
                            tree.push(id);
                            if (tree.length>last_tree_length &&
                                last_tree_length > 0) {
                                change._tree_branches.push(
                                    tree.length - 1);
                            }
                        });
                        if (tree.length > max_tree_columns) {
                            max_tree_columns = tree.length;
                        }
                        if (tree.length > pipeline_max_tree_columns) {
                            pipeline_max_tree_columns = tree.length;
                        }
                        change._tree = tree.slice(0);  // make a copy
                        last_tree_length = tree.length;
                    });
                });
                change_queue._tree_columns = max_tree_columns;
            });
            pipeline._tree_columns = pipeline_max_tree_columns;
            return count;
        },

        get_sparkline_url: function(pipeline_name) {
            if (zuul.graphite_url !== '') {
                if (!(pipeline_name in zuul_sparkline_urls)) {
                    zuul_sparkline_urls[pipeline_name] = $.fn.graphite.geturl({
                        url: zuul.graphite_url,
                        from: "-8hours",
                        width: 100,
                        height: 26,
                        margin: 0,
                        hideLegend: true,
                        hideAxes: true,
                        hideGrid: true,
                        target: [
                            "color(stats.gauges.zuul.pipeline."+pipeline_name+".current_changes, '6b8182')"
                        ]
                    });
                }
                return zuul_sparkline_urls[pipeline_name];
            }
            return false;
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

        $pipelines = $('<div class="row"></div>');
        var $zuulVersion = $('<p>Zuul version: <span id="zuul-version-span">' +
                         '</span></p>');
        var $lastReconf = $('<p>Last reconfigured: ' +
                        '<span id="last-reconfigured-span"></span></p>');

        $container = $('#zuul-container').append($msg, $indicator,
                                                 $queueInfo, $control_form,
                                                 $pipelines, $zuulVersion,
                                                 $lastReconf);

        //zuul.graphite_url = 'http://graphite.openstack.org/render/'
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
