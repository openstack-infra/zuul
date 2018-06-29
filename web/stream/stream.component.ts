// Copyright 2018 Red Hat, Inc.
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
declare var BuiltinConfig: object

import { Component, OnInit } from '@angular/core'
import { ActivatedRoute } from '@angular/router'

import ZuulService from '../zuul/zuul.service'

function escapeLog (text) {
  const pattern = /[<>&"']/g

  return text.replace(pattern, function (match) {
    return '&#' + match.charCodeAt(0) + ';'
  })
}

@Component({
  styles: [require('./stream.component.css').toString()],
  template: require('./stream.component.html')
})
export default class StreamComponent implements OnInit {

  constructor(private route: ActivatedRoute, private zuul: ZuulService) {}

  ngOnInit() {
    this.startStream()
  }

  startStream () {
    const pageUpdateInMS = 250
    let receiveBuffer = ''

    setInterval(function () {
      console.log('autoScroll')
      if (receiveBuffer !== '') {
        document.getElementById('zuulstreamcontent').innerHTML += receiveBuffer
        receiveBuffer = ''
        if ((<HTMLInputElement>document.getElementById('autoscroll')).checked) {
          window.scrollTo(0, document.body.scrollHeight)
        }
      }
    }, pageUpdateInMS)

    const queryParamMap = this.route.snapshot.queryParamMap
    const tenant = this.route.snapshot.paramMap.get('tenant')

    const params = {
      uuid: queryParamMap.get('uuid')
    }
    if (queryParamMap.has('logfile')) {
      params['logfile'] = queryParamMap.get('logfile')
      const logfileSuffix = `(${params['logfile']})`
    }
    if (typeof BuiltinConfig !== 'undefined') {
      params['websocket_url'] = BuiltinConfig['websocket_url']
    } else if (queryParamMap.has('websocket_url')) {
      params['websocket_url'] = queryParamMap.get('websocket_url')
    } else {
      params['websocket_url'] = this.zuul.getWebsocketUrl(
        'console-stream', tenant)
    }
    const ws = new WebSocket(params['websocket_url'])

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
}
