/* global ZUUL_API_URL */
// @licstart  The following is the entire license notice for the
// JavaScript code in this page.
//
// Copyright 2017 Red Hat
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

// TODO(mordred) This should be encapsulated in an Angular Service singleton
// that fetches the other things from the info endpoint.
export function getSourceUrl (filename, $location) {
  if (typeof ZUUL_API_URL !== 'undefined') {
    return ZUUL_API_URL + '/' + filename
  } else {
    return filename
  }
}
