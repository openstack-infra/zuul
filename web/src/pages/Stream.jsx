/* global clearTimeout, setTimeout, JSON, URLSearchParams */
// Copyright 2018 Red Hat, Inc
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

import * as React from 'react'
import PropTypes from 'prop-types'
import { connect } from 'react-redux'
import Sockette from 'sockette'
import {Checkbox, Form, FormGroup, FormControl} from 'patternfly-react'

import 'xterm/dist/xterm.css'
import { Terminal } from 'xterm'
import * as fit from 'xterm/lib/addons/fit/fit'
import * as weblinks from 'xterm/lib/addons/webLinks/webLinks'
import * as search from 'xterm/lib/addons/search/search'

import { getStreamUrl } from '../api'

Terminal.applyAddon(fit)
Terminal.applyAddon(weblinks)
Terminal.applyAddon(search)

class StreamPage extends React.Component {
  static propTypes = {
    match: PropTypes.object.isRequired,
    location: PropTypes.object.isRequired,
    tenant: PropTypes.object
  }

  state = {
    searchRegex: false,
    searchCaseSensitive: false,
    searchWholeWord: false,
  }

  constructor() {
    super()
    this.receiveBuffer = ''
    this.displayRef = React.createRef()
    this.lines = []
  }

  componentWillUnmount () {
    if (this.ws) {
      console.log('Remove ws')
      this.ws.close()
    }
  }

  onMessage = (message) => {
    this.term.write(message)
  }

  onResize = () => {
    // Note: We call proposeGeometry to get the number of cols and rows that
    // fit into the parent element. However the number of rows is not detected
    // correctly so we derive this directly from the window height.
    const geometry = this.term.proposeGeometry()
    if (geometry) {
      const cellHeight = this.term._core.renderer.dimensions.actualCellHeight
      const height = window.innerHeight - this.term.element.offsetTop - 10

      const rows = Math.max(Math.floor(height / cellHeight), 10)
      const cols = Math.max(geometry.cols, 10)

      if (this.term.rows !== rows || this.term.cols !== cols) {
        this.term.resize(cols, rows)
      }
    }
  }

  componentDidMount() {
    const params = {
      uuid: this.props.match.params.buildId
    }
    const urlParams = new URLSearchParams(this.props.location.search)
    const logfile = urlParams.get('logfile')
    if (logfile) {
      params.logfile = logfile
    }
    document.title = 'Zuul Stream | ' + params.uuid.slice(0, 7)

    const term = new Terminal()

    term.webLinksInit()
    term.setOption('fontSize', 12)
    term.setOption('scrollback', 1000000)
    term.setOption('disableStdin', true)
    term.setOption('convertEol', true)

    // Block all keys but page up/down. This needs to be done so ctrl+c can
    // be used to copy text from the terminal.
    term.attachCustomKeyEventHandler(function (e) {
      return e.key === 'PageDown' || e.key === 'PageUp'
    })

    term.open(this.terminal)
    term.focus()

    this.ws = new Sockette(getStreamUrl(this.props.tenant.apiPrefix), {
      timeout: 5e3,
      maxAttempts: 3,
      onopen: () => {
        console.log('onopen')
        this.ws.send(JSON.stringify(params))
      },
      onmessage: e => {
        this.onMessage(e.data)
      },
      onreconnect: e => {
        console.log('Reconnecting...', e)
      },
      onmaximum: e => {
        console.log('Stop Attempting!', e)
      },
      onclose: e => {
       console.log('onclose', e)
       this.onMessage('\n--- END OF STREAM ---\n')
      },
      onerror: e => {
       console.log('onerror:', e)
      }
    })

    this.term = term

    term.element.style.padding = '5px'
    this.onResize()
    window.addEventListener('resize', this.onResize)
  }

  handleCheckBoxRegex = (e) => {
    this.setState({searchRegex: e.target.checked})
  }

  handleCheckBoxCaseSensitive = (e) => {
    this.setState({searchCaseSensitive: e.target.checked})
  }

  handleCheckBoxWholeWord = (e) => {
    this.setState({searchWholeWord: e.target.checked})
  }

  getSearchOptions = () => {
    return {
      regex: this.state.searchRegex,
      wholeWord: this.state.searchWholeWord,
      caseSensitive: this.state.searchCaseSensitive,
    }
  }

  handleKeyPress = (e) => {
    const searchOptions = this.getSearchOptions()
    searchOptions.incremental = e.key !== 'Enter'
    if (e.key === 'Enter') {
      // Don't reload the page on enter
      e.preventDefault()
    }
    if (e.key === 'Enter' && e.shiftKey) {
      this.term.findPrevious(e.target.value, searchOptions)
    } else {
      this.term.findNext(e.target.value, searchOptions)
    }
  }

  render () {
    return (
      <React.Fragment>
        <Form inline>
          <FormGroup controlId='stream'>
            <FormControl
              type='text'
              placeholder='search'
              onKeyPress={this.handleKeyPress}
            />
            &nbsp; Use regex:&nbsp;
            <Checkbox
              checked={this.state.searchRegex}
              onChange={this.handleCheckBoxRegex}>
            </Checkbox>
            &nbsp; Case sensitive:&nbsp;
            <Checkbox
              checked={this.state.searchCaseSensitive}
              onChange={this.handleCheckBoxCaseSensitive}>
            </Checkbox>
            &nbsp; Whole word:&nbsp;
            <Checkbox
              checked={this.state.searchWholeWord}
              onChange={this.handleCheckBoxWholeWord}>
            </Checkbox>
          </FormGroup>
        </Form>
        <div ref={ref => this.terminal = ref}/>
      </React.Fragment>
    )
  }
}


export default connect(state => ({tenant: state.tenant}))(StreamPage)
