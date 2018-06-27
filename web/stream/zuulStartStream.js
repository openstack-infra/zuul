/* global URL, WebSocket, BuiltinConfig */
// Client script for Zuul Log Streaming
//
// Copyright 2017 BMW Car IT GmbH
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

function escapeLog (text) {
  const pattern = /[<>&"']/g

  return text.replace(pattern, function (match) {
    return '&#' + match.charCodeAt(0) + ';'
  })
}

function zuulStartStream (tenant, zuulService) {
  let pageUpdateInMS = 250
  let receiveBuffer = ''

  setInterval(function () {
    console.log('autoScroll')
    if (receiveBuffer !== '') {
      document.getElementById('zuulstreamcontent').innerHTML += receiveBuffer
      receiveBuffer = ''
      if (document.getElementById('autoscroll').checked) {
        window.scrollTo(0, document.body.scrollHeight)
      }
    }
  }, pageUpdateInMS)

  let url = new URL(window.location)

  let params = {
    uuid: url.searchParams.get('uuid')
  }
  document.getElementById('pagetitle').innerHTML = params['uuid']
  if (url.searchParams.has('logfile')) {
    params['logfile'] = url.searchParams.get('logfile')
    let logfileSuffix = `(${params['logfile']})`
    document.getElementById('pagetitle').innerHTML += logfileSuffix
  }
  if (typeof BuiltinConfig !== 'undefined') {
    params['websocket_url'] = BuiltinConfig.websocket_url
  } else if (url.searchParams.has('websocket_url')) {
    params['websocket_url'] = url.searchParams.get('websocket_url')
  } else {
    params['websocket_url'] = zuulService.getWebsocketUrl(
      'console-stream', tenant)
  }
  let ws = new WebSocket(params['websocket_url'])

  ws.onmessage = function (event) {
    console.log('onmessage')
    receiveBuffer = receiveBuffer + escapeLog(event.data)
  }

  ws.onopen = function (event) {
    console.log('onopen')
    ws.send(JSON.stringify(params))
  }

  ws.onclose = function (event) {
    console.log('onclose')
    receiveBuffer = receiveBuffer + '\n--- END OF STREAM ---\n'
  }
}

export default zuulStartStream
