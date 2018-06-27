/* global jQuery, URL, DemoStatusBasic, DemoStatusOpenStack, DemoStatusTree, BuiltinConfig */
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

import 'bootstrap/dist/css/bootstrap.css'
import 'jquery-visibility/jquery-visibility'
import 'graphitejs/jquery.graphite.js'
import angular from 'angular'

import './styles/zuul.css'
import './jquery.zuul'
import { getSourceUrl } from './util'

/**
 * @return The $.zuul instance
 */
function zuulStart ($, $location) {
  // Start the zuul app (expects default dom)

  let $container, $indicator

  let url = new URL(window.location)
  let params = {
    // graphite_url: 'http://graphite.openstack.org/render/'
  }

  if (typeof BuiltinConfig !== 'undefined') {
    params['source'] = BuiltinConfig.api_endpoint + '/' + 'status'
  } else if (url.searchParams.has('source_url')) {
    params['source'] = url.searchParams.get('source_url') + '/' + 'status'
  } else if (url.searchParams.has('demo')) {
    let demo = url.searchParams.get('demo') || 'basic'
    if (demo === 'basic') {
      params['source_data'] = DemoStatusBasic
    } else if (demo === 'openstack') {
      params['source_data'] = DemoStatusOpenStack
    } else if (demo === 'tree') {
      params['source_data'] = DemoStatusTree
    }
  } else {
    params['source'] = getSourceUrl('status', $location)
  }

  let zuul = $.zuul(params)

  zuul.jq.on('update-start', function () {
    $container.addClass('zuul-container-loading')
    $indicator.addClass('zuul-spinner-on')
  })

  zuul.jq.on('update-end', function () {
    $container.removeClass('zuul-container-loading')
    setTimeout(function () {
      $indicator.removeClass('zuul-spinner-on')
    }, 500)
  })

  zuul.jq.one('update-end', function () {
    // Do this asynchronous so that if the first update adds a
    // message, it will not animate while we fade in the content.
    // Instead it simply appears with the rest of the content.
    setTimeout(function () {
      // Fade in the content
      $container.addClass('zuul-container-ready')
    })
  })

  $(function ($) {
    // DOM ready
    $container = $('#zuul-container')
    $indicator = $('#zuul-spinner')
    $('#zuul_controls').append(zuul.app.controlForm())

    zuul.app.schedule()

    $(document).on({
      'show.visibility': function () {
        zuul.options.enabled = true
        zuul.app.update()
      },
      'hide.visibility': function () {
        zuul.options.enabled = false
      }
    })
  })

  return zuul
}

if (module.hot) {
  // This doesn't fully work with our jquery plugin because $.zuul is already
  // instantiated. Leaving it here to show where a hook can happen if we can
  // figure out a way to live update it. When it's not there, an update to
  // jquery.zuul.js triggers a page reload.
  // module.hot.accept('./jquery.zuul', function() {
  //   console.log('Accepting the updated module!');
  // })
}

angular.module('zuulStatus', [], function ($locationProvider) {
  $locationProvider.html5Mode({
    enabled: true,
    requireBase: false,
    rewriteLinks: false
  })
  $locationProvider.hashPrefix('')
}).controller(
  'mainController', function ($location) {
    zuulStart(jQuery, $location)
  }
)
