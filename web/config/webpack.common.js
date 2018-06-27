const path = require('path')
const webpack = require('webpack')
const HtmlWebpackPlugin = require('html-webpack-plugin')
const ForkTsCheckerWebpackPlugin = require('fork-ts-checker-webpack-plugin')

module.exports = {
  entry: './web/main.ts',
  resolve: {
    extensions: [ '.tsx', '.ts', '.js' ]
  },
  output: {
    filename: '[name].js',
    // path.resolve(__dirname winds up relative to the config dir
    path: path.resolve(__dirname, '../../zuul/web/static'),
    publicPath: ''
  },
  // Some folks prefer "cheaper" source-map for dev and one that is more
  // expensive to build for prod. Debugging without the full source-map sucks,
  // so define it here in common.
  devtool: 'source-map',
  optimization: {
    runtimeChunk: true,
    splitChunks: {
      cacheGroups: {
        commons: {
          test: /node_modules/,
          name: 'vendor',
          chunks: 'all'
        }
      }
    }
  },
  plugins: [
    new ForkTsCheckerWebpackPlugin(),
    new webpack.ProvidePlugin({
        $: 'jquery/dist/jquery',
        jQuery: 'jquery/dist/jquery',
    }),
    // Each of the entries below lists a specific 'chunk' which is one of the
    // entry items from above. We can collapse this to just do one single
    // output file.
    new HtmlWebpackPlugin({
      filename: 'status.html',
      template: 'web/config/main.ejs',
      title: 'Zuul Status'
    }),
    new HtmlWebpackPlugin({
      title: 'Zuul Builds',
      template: 'web/config/main.ejs',
      filename: 'builds.html'
    }),
    new HtmlWebpackPlugin({
      title: 'Zuul Jobs',
      template: 'web/config/main.ejs',
      filename: 'jobs.html'
    }),
    new HtmlWebpackPlugin({
      title: 'Zuul Tenants',
      template: 'web/config/main.ejs',
      filename: 'tenants.html'
    }),
    new HtmlWebpackPlugin({
      title: 'Zuul Console Stream',
      template: 'web/config/main.ejs',
      filename: 'stream.html'
    })
  ],
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: /node_modules/,
        use: {
          loader: 'ts-loader',
          options: {
            // disable type checker - we will use it in fork plugin
            transpileOnly: true
          }
        }
      },
      {
        test: /\.js$/,
        exclude: /node_modules/,
        use: [
          'babel-loader'
        ]
      },
      {
        test: /.css$/,
        use: [
          'style-loader',
          'css-loader'
        ]
      },
      {
        test: /\.(png|svg|jpg|gif)$/,
        use: ['file-loader'],
      },
      // The majority of the rules below are all about getting bootstrap copied
      // appropriately.
      {
        test: /\.woff(2)?(\?v=\d+\.\d+\.\d+)?$/,
        use: {
          loader: 'url-loader',
          options: {
            limit: 10000,
            mimetype: 'application/font-woff'
          }
        }
      },
      {
        test: /\.ttf(\?v=\d+\.\d+\.\d+)?$/,
        use: {
          loader: 'url-loader',
          options: {
            limit: 10000,
            mimetype: 'application/octet-stream'
          }
        }
      },
      {
        test: /\.eot(\?v=\d+\.\d+\.\d+)?$/,
        use: ['file-loader'],
      },
      {
        test: /\.svg(\?v=\d+\.\d+\.\d+)?$/,
        use: {
          loader: 'url-loader',
          options: {
            limit: 10000,
            mimetype: 'image/svg+xml'
          }
        }
      },
      {
        test: /\.html$/,
        use: ['html-loader'],
        exclude: /node_modules/
      }
    ]
  }
};
