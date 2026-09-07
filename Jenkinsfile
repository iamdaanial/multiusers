pipeline {
    agent any

    environment {
        IMAGE = "daanial24/multiusers-portal"
        TAG   = "v${BUILD_NUMBER}"
    }

    stages {
        stage('Build') {
            steps {
                sh 'docker build -t $IMAGE:$TAG portal'
            }
        }

        stage('Push') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub',
                                                  usernameVariable: 'USER',
                                                  passwordVariable: 'PASS')]) {
                    sh 'echo $PASS | docker login -u $USER --password-stdin'
                    sh 'docker push $IMAGE:$TAG'
                }
            }
        }

        stage('Deploy') {
            steps {
                sh 'kubectl set image deployment/portal portal=$IMAGE:$TAG'
                sh 'kubectl rollout status deployment/portal'
            }
        }
    }
}
