// Client script for Zuul status page
//
// Copyright 2012 OpenStack Foundation
// Copyright 2013 Timo Tijhof
// Copyright 2013 Wikimedia Foundation
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

(function ($) {
    var $container, $msg, $msgWrap, $indicator, $queueInfo, $queueEventsNum, $queueResultsNum, $pipelines,
        prevHtml, xhr, zuul, $jq,
        demo = location.search.match(/[?&]demo=([^?&]*)/),
        source = demo ?
            './status-' + (demo[1] || 'basic') + '.json-sample' :
            'status.json';

    zuul = {
        enabled: true,

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

            xhr = $.ajax({
                url: source,
                dataType: 'json',
                cache: false
            })
            .done(function (data) {
                var html = '';
                data = data || {};

                if ('message' in data) {
                    $msg.html(data.message);
                    $msgWrap.removeClass('zuul-msg-wrap-off');
                } else {
                    $msg.empty();
                    $msgWrap.addClass('zuul-msg-wrap-off');
                }

                $.each(data.pipelines, function (i, pipeline) {
                    html += zuul.format.pipeline(pipeline);
                });

                // Only re-parse the DOM if we have to
                if (html !== prevHtml) {
                    prevHtml = html;
                    $pipelines.html(html);
                }

                $queueEventsNum.text(
                    data.trigger_event_queue ? data.trigger_event_queue.length : '0'
                );
                $queueResultsNum.text(
                    data.result_event_queue ? data.result_event_queue.length : '0'
                );
            })
            .fail(function (err, jqXHR, errMsg) {
                $msg.text(source + ': ' + errMsg).show();
                $msgWrap.removeClass('zuul-msg-wrap-off');
            })
            .complete(function () {
                xhr = undefined;
                zuul.emit('update-end');
            });

            return xhr;
        },

        format: {
            change: function (change) {
                var html = '<div class="well well-small zuul-change"><ul class="nav nav-list">',
                    id = change.id,
                    url = change.url;

                html += '<li class="nav-header">' + change.project;
                if (id.length === 40) {
                    id = id.substr(0, 7);
                }
                html += ' <span class="zuul-change-id">';
                if (url !== null) {
                    html += '<a href="' + url + '">';
                }
                html += id;
                if (url !== null) {
                    html += '</a>';
                }
                html += '</span></li>';

                $.each(change.jobs, function (i, job) {
                    var result = job.result ? job.result.toLowerCase() : null,
                        resultClass = 'zuul-result label';
                    if (result === null) {
                        result = job.url ? 'in progress' : 'queued';
                    }
                    switch (result) {
                    case 'success':
                        resultClass += ' label-success';
                        break;
                    case 'failure':
                        resultClass += ' label-important';
                        break;
                    case 'lost':
                    case 'unstable':
                        resultClass += ' label-warning';
                        break;
                    }
                    html += '<li class="zuul-change-job">';
                    html += job.url !== null ?
                        '<a href="' + job.url + '" class="zuul-change-job-link">' :
                        '<span class="zuul-change-job-link">';
                    html += job.name;
                    html += ' <span class="' + resultClass + '">' + result + '</span>';
                    if (job.voting === false) {
                        html += ' <span class="muted">(non-voting)</span>';
                    }
                    html += job.url !== null ? '</a>' : '</span>';
                    html += '</li>';
                });

                html += '</ul></div>';
                return html;
            },

            pipeline: function (pipeline) {
                var html = '<div class="zuul-pipeline span4"><h3>' +
                    pipeline.name + '</h3>';
                if (typeof pipeline.description === 'string') {
                    html += '<p><small>' + pipeline.description + '</small></p>';
                }

                $.each(pipeline.change_queues, function (queueNum, changeQueue) {
                    $.each(changeQueue.heads, function (headNum, changes) {
                        if (pipeline.change_queues.length > 1 && headNum === 0) {
                            var name = changeQueue.name;
                            html += '<p>Queue: <abbr title="' + name + '">';
                            if (name.length > 32) {
                                name = name.substr(0, 32) + '...';
                            }
                            html += name + '</abbr></p>';
                        }
                        $.each(changes, function (changeNum, change) {
                            // If there are multiple changes in the same head it means they're connected
                            if (changeNum > 0) {
                                html += '<div class="zuul-change-arrow">&uarr;</div>';
                            }
                            html += zuul.format.change(change);
                        });
                    });
                });

                html += '</div>';
                return html;
            }
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
        }
    };

    $jq = $(zuul);

    $jq.on('update-start', function () {
        $container.addClass('zuul-container-loading');
        $indicator.addClass('zuul-spinner-on');
    });

    $jq.on('update-end', function () {
        $container.removeClass('zuul-container-loading');
        setTimeout(function () {
            $indicator.removeClass('zuul-spinner-on');
        }, 550);
    });

    $jq.one('update-end', function () {
        // Do this asynchronous so that if the first update adds a message, it will not animate
        // while we fade in the content. Instead it simply appears with the rest of the content.
        setTimeout(function () {
            $container.addClass('zuul-container-ready'); // Fades in the content
        });
    });

    $(function ($) {
        $msg = $('<div class="zuul-msg alert alert-error"></div>');
        $msgWrap = $msg.wrap('<div class="zuul-msg-wrap zuul-msg-wrap-off"></div>').parent();
        $indicator = $('<span class="btn pull-right zuul-spinner">updating <i class="icon-refresh"></i></span>');
        $queueInfo = $('<p>Queue lengths: <span>0</span> events, <span>0</span> results.</p>');
        $queueEventsNum =  $queueInfo.find('span').eq(0);
        $queueResultsNum =  $queueEventsNum.next();
        $pipelines = $('<div class="row"></div>');

        $container = $('#zuul-container').append($msgWrap, $indicator, $queueInfo, $pipelines);

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
