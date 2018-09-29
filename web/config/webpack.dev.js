const path = require('path');
const webpack = require('webpack');
const Merge = require('webpack-merge');
const CommonConfig = require('./webpack.common.js');

module.exports = Merge(CommonConfig, {
  mode: 'development',
  // Enable Hot Module Replacement for devServer
  devServer: {
    hot: true,
    contentBase: path.resolve(__dirname, './zuul/web/static'),
    publicPath: '/'
  },
  plugins: [
    new webpack.HotModuleReplacementPlugin(),
    // We only need to bundle the demo files when we're running locally
    new webpack.ProvidePlugin({
        DemoStatusBasic: '../config/status-basic.json',
        DemoStatusOpenStack: '../config/status-openstack.json',
        DemoStatusTree: '../config/status-tree.json'
    }),
  ]
})
