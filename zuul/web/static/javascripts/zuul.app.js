// Client script for Zuul status page
//
// @licstart  The following is the entire license notice for the
// JavaScript code in this page.
//
// Copyright 2013 OpenStack Foundation
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
//
// @licend  The above is the entire license notice
// for the JavaScript code in this page.

/*exported zuul_build_dom, zuul_start */

function zuul_build_dom($, container) {
    // Build a default-looking DOM
    var default_layout = '<div class="container">'
        + '<div class="zuul-container" id="zuul-container">'
        + '<div style="display: none;" class="alert" id="zuul_msg"></div>'
        + '<button class="btn pull-right zuul-spinner">updating <span class="glyphicon glyphicon-refresh"></span></button>'
        + '<p>Queue lengths: <span id="zuul_queue_events_num">0</span> events, <span id="zuul_queue_management_events_num">0</span> management events, <span id="zuul_queue_results_num">0</span> results.</p>'
        + '<div id="zuul_controls"></div>'
        + '<div id="zuul_pipelines" class="row"></div>'
        + '<p>Zuul version: <span id="zuul-version-span"></span></p>'
        + '<p>Last reconfigured: <span id="last-reconfigured-span"></span></p>'
        + '</div></div>';

    $(function ($) {
        // DOM ready
        var $container = $(container);
        $container.html(default_layout);
    });
}

/**
 * @return The $.zuul instance
 */
function zuul_start($) {
    // Start the zuul app (expects default dom)

    var $container, $indicator;
    var demo = location.search.match(/[?&]demo=([^?&]*)/),
        source_url = location.search.match(/[?&]source_url=([^?&]*)/),
        source = demo ? './status-' + (demo[1] || 'basic') + '.json-sample' :
            'status.json';
    source = source_url ? source_url[1] : source;

    var zuul = $.zuul({
        source: source,
        //graphite_url: 'http://graphite.openstack.org/render/'
    });

    zuul.jq.on('update-start', function () {
        $container.addClass('zuul-container-loading');
        $indicator.addClass('zuul-spinner-on');
    });

    zuul.jq.on('update-end', function () {
        $container.removeClass('zuul-container-loading');
        setTimeout(function () {
            $indicator.removeClass('zuul-spinner-on');
        }, 500);
    });

    zuul.jq.one('update-end', function () {
        // Do this asynchronous so that if the first update adds a
        // message, it will not animate while we fade in the content.
        // Instead it simply appears with the rest of the content.
        setTimeout(function () {
            // Fade in the content
            $container.addClass('zuul-container-ready');
        });
    });

    $(function ($) {
        // DOM ready
        $container = $('#zuul-container');
        $indicator = $('#zuul-spinner');
        $('#zuul_controls').append(zuul.app.control_form());

        zuul.app.schedule();

        $(document).on({
            'show.visibility': function () {
                zuul.options.enabled = true;
                zuul.app.update();
            },
            'hide.visibility': function () {
                zuul.options.enabled = false;
            }
        });
    });

    return zuul;
}
