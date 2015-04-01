#!/bin/bash
BASE_DIR=$(cd $(dirname $0); pwd)
DEST_DIR=$BASE_DIR/public_html
echo "Destination: $DEST_DIR"

echo "Fetching jquery.min.js..."
curl -L --silent http://code.jquery.com/jquery.min.js > $DEST_DIR/jquery.min.js

echo "Fetching jquery-visibility.min.js..."
curl -L --silent https://raw.githubusercontent.com/mathiasbynens/jquery-visibility/master/jquery-visibility.js > $DEST_DIR/jquery-visibility.js

echo "Fetching jquery.graphite.js..."
curl -L --silent https://github.com/prestontimmons/graphitejs/archive/master.zip > jquery-graphite.zip
unzip -q -o jquery-graphite.zip -d $DEST_DIR/
mv $DEST_DIR/graphitejs-master/jquery.graphite.js $DEST_DIR/
rm -R jquery-graphite.zip $DEST_DIR/graphitejs-master

echo "Fetching bootstrap..."
curl -L --silent https://github.com/twbs/bootstrap/releases/download/v3.1.1/bootstrap-3.1.1-dist.zip > bootstrap.zip
unzip -q -o bootstrap.zip -d $DEST_DIR/
mv $DEST_DIR/bootstrap-3.1.1-dist $DEST_DIR/bootstrap
rm bootstrap.zip
