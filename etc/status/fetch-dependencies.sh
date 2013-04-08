#!/bin/bash
BASE_DIR=$(cd $(dirname $0); pwd)
echo "Destination: $BASE_DIR/public_html"
echo "Fetching jquery.min.js..."
curl --silent http://code.jquery.com/jquery.min.js > $BASE_DIR/public_html/jquery.min.js
echo "Fetching jquery-visibility.min.js..."
curl --silent https://raw.github.com/mathiasbynens/jquery-visibility/master/jquery-visibility.min.js > $BASE_DIR/public_html/jquery-visibility.min.js
echo "Fetching bootstrap..."
curl --silent http://twitter.github.io/bootstrap/assets/bootstrap.zip > bootstrap.zip && unzip -q -o bootstrap.zip -d $BASE_DIR/public_html/ && rm bootstrap.zip
